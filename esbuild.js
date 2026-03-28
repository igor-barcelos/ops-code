const esbuild = require('esbuild');

const isWatch = process.argv.includes('--watch');

const extensionConfig = {
    entryPoints: ['src/extension.ts'],
    bundle: true,
    platform: 'node',
    external: ['vscode'],
    outfile: 'dist/extension.js',
    sourcemap: true,
};

const viewerConfig = {
    entryPoints: ['media/viewer.ts'],
    bundle: true,
    platform: 'browser',
    outfile: 'media/viewer.js',
    sourcemap: true,
};

if (isWatch) {
    Promise.all([
        esbuild.context(extensionConfig).then((ctx) => ctx.watch()),
        esbuild.context(viewerConfig).then((ctx) => ctx.watch()),
    ]).catch(() => process.exit(1));
} else {
    Promise.all([
        esbuild.build(extensionConfig),
        esbuild.build(viewerConfig),
    ]).catch(() => process.exit(1));
}
