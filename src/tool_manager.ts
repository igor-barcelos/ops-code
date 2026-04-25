import { spawn } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { Outputs, ToolOutput } from './types';

export async function exec(
    modelDir: string,
    py_path: string,
    extensionUri: vscode.Uri,
    outputs: Outputs,
    tools: string[],
): Promise<ToolOutput[]> {
    if (tools.length === 0) { return []; }

    const dir = path.join(modelDir, 'tools');
    if (!fs.existsSync(dir)) { return []; }

    const toolFiles = tools
        .map((name) => ({ name, path: path.join(dir, `${name}.py`) }))
        .filter((t) => fs.existsSync(t.path));

    if (toolFiles.length === 0) { return []; }

    const runner = vscode.Uri.joinPath(extensionUri, 'python', 'tools_runner.py').fsPath;
    const payload = JSON.stringify({ outputs });

    const runs = await Promise.allSettled(
        toolFiles.map(async (t) => [t.name, await run(py_path, runner, t.path, payload)] as const),
    );
    const results: ToolOutput[] = [];
    for (const r of runs) {
        if (r.status === 'fulfilled') {
            const [name, { elements }] = r.value;
            results.push({ name, elements });
        } else {
            console.error('[ops-code] tool failed:', r.reason);
        }
    }
    return results;
}

function run(py_path: string, runner: string, toolPath: string, payload: string): Promise<Omit<ToolOutput, 'name'>> {
    return new Promise((resolve, reject) => {
        const proc = spawn(py_path, [runner, toolPath]);
        let stdout = '';
        let stderr = '';
        proc.stdout.on('data', (chunk: Buffer) => { stdout += chunk.toString(); });
        proc.stderr.on('data', (chunk: Buffer) => { stderr += chunk.toString(); });
        proc.on('close', (code) => {
            if (code !== 0) { reject(new Error(stderr.trim() || `python exited ${code}`)); return; }
            try {
                resolve(JSON.parse(stdout.trim()) as Omit<ToolOutput, 'name'>);
            } catch {
                reject(new Error(`failed to parse tool output: ${stdout}`));
            }
        });
        proc.on('error', reject);
        proc.stdin.end(payload);
    });
}
