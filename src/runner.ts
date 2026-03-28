import { spawn } from 'child_process';
import * as vscode from 'vscode';
import { ModelData, AnalysisRunnerOutput } from './types';

export async function pythonPath(): Promise<string> {
    const config = vscode.workspace.getConfiguration('ops-code');
    const userPath = config.get<string>('pythonPath');
    if (userPath && userPath.trim() !== '') {
        return userPath.trim();
    }

    const pythonExt = vscode.extensions.getExtension('ms-python.python');
    if (pythonExt) {
        const api = await pythonExt.activate() as { settings?: { getExecutionDetails?: () => { execCommand?: string[] } } } | undefined;
        const execCommand = api?.settings?.getExecutionDetails?.()?.execCommand;
        if (execCommand && execCommand[0]) {
            return execCommand[0];
        }
    }

    return 'python3';
}

export function intercept(
    pythonPath: string,
    extensionUri: vscode.Uri,
    scriptPath: string,
): Promise<ModelData> {
    return run(pythonPath, extensionUri, 'runner.py', scriptPath);
}

export function analyze(
    pythonPath: string,
    extensionUri: vscode.Uri,
    scriptPath: string,
): Promise<AnalysisRunnerOutput> {
    return run(pythonPath, extensionUri, 'analysis_runner.py', scriptPath) as Promise<AnalysisRunnerOutput>;
}

function run(
    pythonPath: string,
    extensionUri: vscode.Uri,
    runnerFile: string,
    scriptPath: string,
): Promise<ModelData> {
    return new Promise((resolve, reject) => {
        const runnerPath = vscode.Uri.joinPath(extensionUri, 'python', runnerFile).fsPath;
        const proc = spawn(pythonPath, [runnerPath, scriptPath]);

        let stdout = '';
        let stderr = '';

        proc.stdout.on('data', (chunk: Buffer) => { stdout += chunk.toString(); });
        proc.stderr.on('data', (chunk: Buffer) => { stderr += chunk.toString(); });

        proc.on('close', () => {
            if (!stdout.trim()) {
                reject(new Error(stderr.trim() || 'No output from Python process'));
                return;
            }
            try {
                resolve(JSON.parse(stdout.trim()) as ModelData);
            } catch {
                reject(new Error(`Failed to parse Python output: ${stdout}`));
            }
        });

        proc.on('error', (err: NodeJS.ErrnoException) => {
            if (err.code === 'ENOENT') {
                reject(new Error(`Python interpreter not found: "${pythonPath}". Set ops-code.pythonPath in settings.`));
            } else {
                reject(err);
            }
        });
    });
}
