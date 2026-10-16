"""Keep native setup checks for runtime changes; always run normal verification."""
import os
import subprocess


def needs_desktop(paths):
    # UI and prose changes still receive the complete Linux test/build/security job.
    # Unknown/new root files conservatively require all desktop platforms.
    ui_or_docs = ('src/', 'public/', 'docs/')
    non_native_files = {'README.md', 'instructions.md', 'index.html', '.github/dependabot.yml'}
    return any(not (path.startswith(ui_or_docs) or path in non_native_files) for path in paths)


def main():
    base = os.environ.get('BASE_SHA', '')
    head = os.environ.get('HEAD_SHA', 'HEAD')
    desktop = True  # Manual, scheduled and first-push runs check every platform.
    if base and base != '0' * 40:
        result = subprocess.run(['git', 'diff', '--name-only', '-z', base, head, '--'],
                                check=False, stdout=subprocess.PIPE)
        if result.returncode == 0:
            desktop = needs_desktop(result.stdout.decode('utf-8').strip('\0').split('\0'))
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
        output.write(f'desktop={str(desktop).lower()}\n')
    print('Native setup: all four platforms' if desktop else 'UI/docs change: normal tests, build and security checks only')


if __name__ == '__main__':
    main()
