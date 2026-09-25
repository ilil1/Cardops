import ts from 'typescript';
import { spawn } from 'node:child_process';

// Nest constructor injection needs TypeScript's emitDecoratorMetadata output.
// Compile with tsc's watch API before starting/restarting the server.
let server;
let stopping = false;
const format = {
  getCanonicalFileName: file => file,
  getCurrentDirectory: ts.sys.getCurrentDirectory,
  getNewLine: () => ts.sys.newLine,
};
const report = diagnostic => process.stdout.write(ts.formatDiagnostic(diagnostic, format));
const host = ts.createWatchCompilerHost('tsconfig.build.json', {}, ts.sys,
  ts.createEmitAndSemanticDiagnosticsBuilderProgram, report, report);
const afterBuild = host.afterProgramCreate;
host.afterProgramCreate = program => {
  afterBuild(program);
  if (ts.getPreEmitDiagnostics(program.getProgram()).some(item => item.category === ts.DiagnosticCategory.Error)) return;
  const start = () => { if (!stopping) server = spawn(process.execPath, ['dist/main.js'], { stdio: 'inherit' }); };
  if (server && server.exitCode === null && server.signalCode === null) {
    server.once('exit', start);
    server.kill('SIGTERM');
  } else start();
};
const watcher = ts.createWatchProgram(host);
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    stopping = true;
    watcher.close();
    if (server && server.exitCode === null) {
      server.once('exit', () => process.exit(0));
      server.kill(signal);
    } else process.exit(0);
  });
}
