import datetime
import os

from os_utils import BackupManager, FileFinder
from models.file import parse, all_tasks, find_block, write_nodes, serialize
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
            nodes = parse(file_path)
            open_tasks = [
                t for t in all_tasks(nodes)
                if t.status in ['todo', 'in progress']
            ]

            if open_tasks:
                if not CatchUpTool.interactive_cleanup(directory, file_path, nodes, open_tasks):
                    return

    @staticmethod
    def interactive_cleanup(directory, file_path, nodes, open_tasks):
        """Interactive cleanup of tasks in a file."""
        lines = serialize(nodes).splitlines(keepends=True)
        pending_changes = []  # [(block, new_status, old_line, new_line)]

        for idx, task in enumerate(open_tasks, 1):
            block = find_block(nodes, task)
            if block is None:
                continue

            line_num = task.line_number
            old_line = block.header.rstrip('\n')

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
                            CatchUpTool._apply_changes(file_path, nodes, pending_changes)
                    return False

                if action == 's':
                    break

                if action in ['d', 't', 'i', 'f']:
                    new_status = {'d': 'done', 't': 'todo', 'i': 'in progress', 'f': 'failed'}[action]
                    old_status = task.status
                    task.status = new_status
                    new_line = task.to_line()
                    task.status = old_status
                    pending_changes.append((block, new_status, old_line, new_line))
                    print("✓ Change queued")
                    break
                else:
                    print("Invalid action. Use: d, t, i, f, s or q")

        if pending_changes:
            rel_path = os.path.relpath(file_path, directory)
            print(f"\n{len(pending_changes)} change(s) in {rel_path}:")

            sorted_changes = sorted(pending_changes, key=lambda x: x[0].task.line_number)

            print("   ┌" + "─" * 76)
            for i, (block, _, old_line, new_line) in enumerate(sorted_changes):
                print(f"{block.task.line_number:4d}{RED} -  {old_line}{RESET}")
                print(f"   │{GREEN} +  {new_line}{RESET}")
                if i < len(sorted_changes) - 1:
                    print("   ├" + "─" * 76)
            print("   └" + "─" * 76)

            confirm = input("Apply all changes? [y/n]: ").strip().lower()
            if confirm == 'y':
                BackupManager.backup(file_path, directory)
                CatchUpTool._apply_changes(file_path, nodes, pending_changes)
                print(f"✓ {len(pending_changes)} change(s) saved")
            else:
                print("Changes discarded.")

    @staticmethod
    def _apply_changes(file_path, nodes, pending_changes):
        for block, new_status, _, _ in pending_changes:
            block.set_status(new_status)
        write_nodes(file_path, nodes)
