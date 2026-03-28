import * as path from 'path';
import * as vscode from 'vscode';

export function watch(filePath: string, onChange: () => void): vscode.Disposable {
    const watcher = vscode.workspace.createFileSystemWatcher(
        new vscode.RelativePattern(
            vscode.Uri.file(path.dirname(filePath)),
            path.basename(filePath),
        )
    );

    const debounced = debounce(onChange, 300);
    const subscription = watcher.onDidChange(debounced);

    return {
        dispose: () => {
            subscription.dispose();
            watcher.dispose();
        }
    };
}

function debounce(fn: () => void, delayMs: number): () => void {
    let timer: ReturnType<typeof setTimeout> | null = null;
    return () => {
        if (timer !== null) {
            clearTimeout(timer);
        }
        timer = setTimeout(() => {
            timer = null;
            fn();
        }, delayMs);
    };
}
