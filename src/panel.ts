import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { pythonPath, intercept, analyze } from './runner';
import { exec } from './tool_manager';
import { watch } from './watcher';
import { Outputs, WebViewMessage, ViewerMessage } from './types';

export class Panel {
    private static instance: Panel | undefined;

    private readonly panel: vscode.WebviewPanel;
    private readonly extensionUri: vscode.Uri;
    private readonly scriptPath: string;
    private readonly disposables: vscode.Disposable[] = [];

    private constructor(
        panel: vscode.WebviewPanel,
        extensionUri: vscode.Uri,
        scriptPath: string,
    ) {
        this.panel = panel;
        this.extensionUri = extensionUri;
        this.scriptPath = scriptPath;

        this.panel.webview.html = this.html();

        this.panel.webview.onDidReceiveMessage(
            (msg: ViewerMessage) => {
                if (msg.type === 'ready') {
                    this.load();
                } else if (msg.type === 'runAnalysis') {
                    this.analyze();
                } else if (msg.type === 'screenshot') {
                    this.save(msg.data);
                }
            },
            null,
            this.disposables,
        );

        this.panel.onDidDispose(() => this.dispose(), null, this.disposables);
        this.disposables.push(watch(scriptPath, () => this.load()));
    }

    static screenshot(): void {
        Panel.instance?.post({ type: 'takeScreenshot' });
    }

    static open(extensionUri: vscode.Uri, scriptPath: string): void {
        const column = vscode.window.activeTextEditor?.viewColumn ?? vscode.ViewColumn.Beside;

        if (Panel.instance) {
            Panel.instance.panel.reveal(column);
            return;
        }

        const panel = vscode.window.createWebviewPanel(
            'openSeesViewer',
            'ops-code',
            column,
            {
                enableScripts: true,
                retainContextWhenHidden: true,
                localResourceRoots: [vscode.Uri.joinPath(extensionUri, 'media')],
            },
        );

        Panel.instance = new Panel(panel, extensionUri, scriptPath);
    }

    private async load(): Promise<void> {
        this.post({ type: 'loading' });
        try {
            const py = await pythonPath();
            const data = await intercept(py, this.extensionUri, this.scriptPath);
            this.post({ type: 'modelData', data });
        } catch (err: unknown) {
            this.post({ type: 'error', message: err instanceof Error ? err.message : String(err) });
        }
    }

    private async analyze(): Promise<void> {
        this.post({ type: 'analysisRunning' });
        try {
            const py = await pythonPath();
            const data = await analyze(py, this.extensionUri, this.scriptPath);
            if (data.error) {
                this.post({ type: 'error', message: data.error });
            } else if (data.outputs) {
                this.post({ type: 'analysisData', data: data.outputs, ndf: data.ndf });
                this.runTools(data.outputs, data.tools ?? []);
            }
        } catch (err: unknown) {
            this.post({ type: 'error', message: err instanceof Error ? err.message : String(err) });
        }
    }

    private async runTools(outputs: Outputs, tools: string[]): Promise<void> {
        const modelDir = path.dirname(this.scriptPath);
        const py = await pythonPath();
        try {
            const data = await exec(modelDir, py, this.extensionUri, outputs, tools);
            if (data.length > 0) { this.post({ type: 'toolUse', data }); }
        } catch (err: unknown) {
            this.post({ type: 'error', message: err instanceof Error ? err.message : String(err) });
        }
    }

    private async save(dataUrl: string): Promise<void> {
        const ts = new Date().toISOString().replace('T', '_').replace(/:/g, '-').slice(0, 19);
        const filePath = this.scriptPath.replace(/\.py$/i, '') + `_${ts}.png`;
        const base64 = dataUrl.replace(/^data:image\/png;base64,/, '');
        fs.writeFileSync(filePath, Buffer.from(base64, 'base64'));
        await vscode.env.clipboard.writeText(filePath);
        vscode.window.setStatusBarMessage('Screenshot saved', 3000);
    }

    private post(message: WebViewMessage): void {
        this.panel.webview.postMessage(message);
    }

    private html(): string {
        const n = nonce();
        const viewerJsUri = this.panel.webview.asWebviewUri(
            vscode.Uri.joinPath(this.extensionUri, 'media', 'viewer.js'),
        );
        const htmlPath = vscode.Uri.joinPath(this.extensionUri, 'media', 'viewer.html').fsPath;
        return fs.readFileSync(htmlPath, 'utf-8')
            .replace(/NONCE_PLACEHOLDER/g, n)
            .replace('VIEWER_JS_URI', viewerJsUri.toString());
    }

    dispose(): void {
        Panel.instance = undefined;
        this.panel.dispose();
        for (const d of this.disposables) { d.dispose(); }
        this.disposables.length = 0;
    }
}

function nonce(): string {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    return Array.from({ length: 32 }, () => chars[Math.floor(Math.random() * chars.length)]).join('');
}
