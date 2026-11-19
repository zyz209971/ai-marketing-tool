"""Provision a classroom account without putting its password in shell history."""
import argparse
import getpass
from deployment_config import configure

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('username')
    parser.add_argument('--workspace',required=True,help='Same ID grants access to the same workspace')
    args=parser.parse_args()
    configure()
    from app import auth
    auth.init_db()
    password=getpass.getpass('Password (12+ characters): ')
    if password!=getpass.getpass('Confirm password: '):
        raise SystemExit('Passwords do not match')
    try:
        auth.provision(args.username,password,args.workspace)
    except Exception:
        raise SystemExit('Account was not created. Check username uniqueness and password length.') from None
    print('Account created; existing workspaces were not reassigned.')
