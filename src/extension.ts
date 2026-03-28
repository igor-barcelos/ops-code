import * as vscode from 'vscode';
import { Panel } from './panel';

export function activate(context: vscode.ExtensionContext): void {
    context.subscriptions.push(
        vscode.commands.registerCommand('ops-code.run', (uri?: vscode.Uri) => {
            const path = scriptPath(uri);
            if (!path) { vscode.window.showErrorMessage('No Python file selected.'); return; }
            Panel.open(context.extensionUri, path);
        }),
        vscode.commands.registerCommand('ops-code.screenshot', () => {
            Panel.screenshot();
        }),
    );
}

export function deactivate(): void {}

function scriptPath(uri: vscode.Uri | undefined): string | undefined {
    if (uri) { return uri.fsPath; }
    const editor = vscode.window.activeTextEditor;
    if (editor && editor.document.languageId === 'python') { return editor.document.uri.fsPath; }
    return undefined;
}
