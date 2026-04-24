import datetime
import os
from difflib import unified_diff

from models import Task
from os_utils import BackupManager, FileFinder
from parser import TaskParser
from tools.journal_tools.rendering import BOLD, GRAY, GREEN, RED, RESET


class CatchUpTool:
    @staticmethod
    def run(args, directory='.'):
        directory = args[0] if args else directory
        journal_files = FileFinder.find_journal_files(
            directory,
            date_to=datetime.date.today()
        )

        if not journal_files:
            print("No journal files found.")
            return

        for file_path in journal_files:
            tasks = TaskParser.parse_file(file_path)
            open_tasks = [
                task for task in tasks
                if task.status in ['todo', 'in progress']
            ]

            if open_tasks:
                if not CatchUpTool.interactive_cleanup(directory, file_path, open_tasks):
                    return

    @staticmethod
    def interactive_cleanup(directory, file_path, open_tasks: list[Task]):
        """Interactive cleanup of tasks in a file"""
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        pending_changes = []  # [(line_num, old_line, new_line)]

        for idx, task in enumerate(open_tasks, 1):
            line_num = task.line_number
            original_line = lines[line_num - 1].rstrip('\n')

            rel_path = os.path.relpath(file_path, directory)
            context_radius = 2
            start_idx = max(0, line_num - 1 - context_radius)
            end_idx = min(len(lines), line_num + context_radius)

            print(f"\n{idx}/{len(open_tasks)} open tasks in {rel_path} (line {line_num}):")

            print("   ┌" + "─" * 76)
            for i in range(start_idx, end_idx):
                lnum = i + 1
                content = lines[i].rstrip('\n')
                pointer = " →" if lnum == line_num else "  "
                marker = "│"
                if lnum == line_num:
                    line_fmt = f"{BOLD}{lnum:4d}{pointer} {marker} {content}{RESET}"
                else:
                    line_fmt = f"{lnum:4d}{pointer} {marker} {GRAY}{content}{RESET}"
                output = line_fmt[:80]
                if not output.endswith(RESET):
                    output = output + RESET
                print(output)
            print("   └" + "─" * 76)

            while True:
                action = input("Action [d=done, t=todo, i=in progress, f=failed, s=skip, q=quit]: ").strip().lower()

                if action == 'q':
                    if pending_changes:
                        save = input("\nThere are unsaved changes. Save? [y/n]: ").strip().lower()
                        if save == 'y':
                            BackupManager.backup(file_path, directory)
                            CatchUpTool.apply_changes(file_path, pending_changes, lines)
                    return False

                if action == 's':
                    break

                if action in ['d', 't', 'i', 'f']:
                    new_status = {'d': 'done', 't': 'todo', 'i': 'in progress', 'f': 'failed'}[action]
                    task.status = new_status
                    new_line = task.to_line()

                    pending_changes.append((line_num, original_line, new_line))
                    print("✓ Change queued")
                    break
                else:
                    print("Invalid action. Use: d, t, i, f, s or q")

        if pending_changes:
            rel_path = os.path.relpath(file_path, directory)
            print(f"\n{len(pending_changes)} change(s) in {rel_path}:")

            sorted_changes = sorted(pending_changes, key=lambda x: x[0])

            print("   ┌" + "─" * 76)
            for idx, (line_num, old_line, new_line) in enumerate(sorted_changes):
                print(f"{line_num:4d}{RED} -  {old_line}{RESET}")
                print(f"   │{GREEN} +  {new_line}{RESET}")
                if idx < len(sorted_changes) - 1:
                    print("   ├" + "─" * 76)
            print("   └" + "─" * 76)

            confirm = input("Apply all changes? [y/n]: ").strip().lower()
            if confirm == 'y':
                BackupManager.backup(file_path, directory)
                CatchUpTool.apply_changes(file_path, pending_changes, lines)
                print(f"✓ {len(pending_changes)} change(s) saved")
            else:
                print("Changes discarded.")

    @staticmethod
    def apply_changes(file_path, changes, lines):
        """Applies changes to a file and saves it"""
        if not changes:
            return

        changes.sort(key=lambda x: x[0], reverse=True)

        for line_num, old_line, new_line in changes:
            if line_num <= len(lines):
                current_line = lines[line_num - 1].rstrip('\n')
                if current_line == old_line or current_line == new_line:
                    lines[line_num - 1] = new_line + '\n'
                else:
                    print(f"Warning: Line {line_num} in {file_path} has changed. Skipped.")

        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
