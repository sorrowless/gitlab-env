#!/usr/bin/python3
import gitlab, os, re, argparse, sys
from git import Repo

class GitlabProject():
    def __init__(self, url, path, vars_file):
        '''
        Create Gitlab instanse.
        "keep_base_url=True" needs to resolve warning:
        "UserWarning: The base URL in the server response differs from the user-provided base URL (https://gitlab.example.com -> http://gitlab.example.com)."
        '''
        self.gl = gitlab.Gitlab(url, private_token=os.environ['GITLAB_TOKEN'],  keep_base_url=True)
        self.project = self.gl.projects.get(path, lazy=True)                          # Create project's object
        self.project_variables = self.project.variables.list(get_all=True)            # Get variables
        self.vars_dict = {}
        self.parse_dict = {}
        self.vars_file = vars_file

    def gen_vars_dict(self):
        for variable in self.project_variables:                                  # Create dict of environment scopes
            self.vars_dict.update({variable.environment_scope:{}})

        for env_scope in self.vars_dict:                                         # Filling environment scopes by key:value
            for variable in self.project_variables:
                if variable.environment_scope == env_scope:
                    self.vars_dict[env_scope].update({variable.key:variable.value})

    def gen_varfile_json(self):
        with open(self.vars_file, 'w') as f:
            for env in self.vars_dict:
                f.write('###  Environment scope: "{env_scope}" ###\n'.format(env_scope = env))
                tmp_lines = []
                for var in self.vars_dict[env]:
                    f.write('# {key}: "{value}"\n'.format(key = var, value = self.vars_dict[env][var]))
                f.write(''.join(tmp_lines))
                f.write('\n')
        print('Variables are written to the file: "{file}".'.format(file = self.vars_file))

    def print_stdout_json(self):
        for env in self.vars_dict:
            print('###  Environment scope: "{env_scope}" ###'.format(env_scope = env))
            tmp_lines = []
            for var in self.vars_dict[env]:
                re_expression = re.findall(" \${[0-9A-Z_]*}", self.vars_dict[env][var])
                if len(re_expression) > 0:
                    tmp_lines.append('# {key}: "{value}"'.format(key = var, value = self.vars_dict[env][var]))
                    continue
                print('# {key}: "{value}"'.format(key = var, value = self.vars_dict[env][var]))
            print(''.join(tmp_lines))
            print('')

    def print_envs(self):
        print('List of environment scopes: ')
        for env in self.vars_dict:
            print(env)

    def select_envs(self, envs):
        del_list = []
        for env in self.vars_dict:
            if env not in envs:
                del_list.append(env)
        for env in del_list:
            del self.vars_dict[env]
            print('Env "%s" deleted from output.' % env)
        print('')

    def parse_varfile_json(self, force=False):
        var_re = ''
        del_list = []
        with open(self.vars_file, 'r') as f:
            for line in f.readlines():
                env_re = re.findall('Environment scope: "(.*)"', line)
                var_re = re.findall('([a-zA-Z_].*): "(.*)"', line)
                if 'Environment scope:' in line:
                    self.parse_dict.update({env_re[0]:{}})
                    env_scope = env_re[0]
                else:
                    vars = dict((key, value) for key, value in var_re)
                    self.parse_dict[env_scope].update(vars)
        if not force:                                  # If env isn't exist in "self.parse_dict" (vars from file)
            for env in self.vars_dict:                             # remove it from "self.vars_dict" (vars from gitlab)
                if env not in self.parse_dict:                     # for take effect (create, update, delete)
                    del_list.append(env)                      # only to variables existing in  "self.parse_dict"
            for env in del_list:
                del self.vars_dict[env]

    def gen_push_list(self):
        push_list = []
        if self.vars_dict == self.parse_dict:
            print('No changes found.')
        else:
            for env_scope in self.parse_dict:
                for variable in self.parse_dict[env_scope]:
                    if (env_scope not in self.vars_dict) or (variable not in self.vars_dict[env_scope]):
                        push_list.append({'key': variable,
                                          'value': self.parse_dict[env_scope][variable],
                                          'environment_scope': env_scope,
                                          'action':'create'})

                    elif (variable in self.vars_dict[env_scope]) and (self.vars_dict[env_scope][variable] != self.parse_dict[env_scope][variable]):
                        push_list.append({'key': variable,
                                          'value': self.parse_dict[env_scope][variable],
                                          'environment_scope': env_scope,
                                          'action':'update'})

            for env_scope in self.vars_dict:
                for variable in self.vars_dict[env_scope]:
                    if (env_scope not in self.parse_dict):
                        push_list.append({'key': variable,
                                          'environment_scope': env_scope,
                                          'action':'delete'})

                    elif (variable in self.vars_dict[env_scope]) and (variable not in self.parse_dict[env_scope]):
                        push_list.append({'key': variable,
                                          'environment_scope': env_scope,
                                          'action':'delete'})
        return push_list

    def push_vars(self, push_list):
        for i in push_list:
            if i['action'] == 'create':
                self.project.variables.create({'key': i['key'], 'value': i['value'], 'environment_scope': i['environment_scope']})
                print('Created: %s' % i)
            elif i['action'] == 'update':
                self.project.variables.update(i['key'], {'value': i['value']}, filter={'environment_scope': i['environment_scope']})
                print('Updated: %s' % i)
            elif i['action'] == 'delete':
                self.project.variables.delete(i['key'], filter={'environment_scope': i['environment_scope']})
                print('Deleted: %s' % i)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--file', type=str, default='.gitlab-ci-local-variables.yml')
    parser.add_argument('-e', '--envs', nargs='+', help='Choose environment scope (Try --list before).', type=str)
    parser.add_argument('-g', '--get', help='Fetch variables from gitlab.', action='store_true')
    parser.add_argument('-p', '--push', help='Push variables to gitlab.', action='store_true')
    parser.add_argument('--force', help='Force push variables to gitlab.', action='store_true')
    parser.add_argument('-l', '--list', help='List environment scopes.', action='store_true')
    # parser.add_argument('-j', '--json', help='Gen JSON varfile.', action='store_true')

    args = parser.parse_args()
    repo = Repo(os.getcwd())
    _, domain, path = re.split('@|:', repo.remote().url.split('.git')[0])
    url = 'https://' + domain

    project = GitlabProject(url, path, args.file)
    project.gen_vars_dict()

    if args.envs and args.get:
        project.select_envs(args.envs)
        project.gen_varfile_json()
    elif args.get:
        project.gen_varfile_json()
    elif args.push:
        project.parse_varfile_json(args.force)
        push_list = project.gen_push_list()
        project.push_vars(push_list)
    elif not len(sys.argv) > 1:
        project.print_stdout_json()
    elif args.list:
        project.print_envs()
    elif args.envs:
        project.select_envs(args.envs)
        project.print_stdout_json()

if __name__ == '__main__':
    main()
