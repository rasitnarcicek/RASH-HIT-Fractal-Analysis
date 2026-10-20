#!/usr/bin/env node

// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mehmet Raşit Narçiçek

const { spawnSync, spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const REQUIRED_PACKAGES = ['numpy>=1.24.0', 'defusedxml>=0.7.1', 'tinycss2>=1.2.0', 'rich>=13.0.0'];
const REQUIRED_MODULES = ['numpy', 'defusedxml', 'tinycss2', 'rich'];

function findPythonCommand() {
  const candidates = process.platform === 'win32'
    ? ['python', 'py', 'python3']
    : ['python3', 'python'];

  for (const cmd of candidates) {
    try {
      const res = spawnSync(cmd, ['--version'], { encoding: 'utf8', stdio: 'pipe' });
      if (res.status === 0) {
        return cmd;
      }
    } catch (_) {
      // Continue searching
    }
  }
  return null;
}

function checkDependencies(pythonCmd) {
  const checkCode = `
import sys
missing = []
for mod in ${JSON.stringify(REQUIRED_MODULES)}:
    try:
        __import__(mod)
    except ImportError:
        missing.append(mod)
if missing:
    sys.exit(1)
`;
  const res = spawnSync(pythonCmd, ['-c', checkCode], { encoding: 'utf8', stdio: 'pipe' });
  return res.status === 0;
}

function installDependencies(pythonCmd) {
  console.log('\n📦 [RASH-HIT Fractal Analysis] First-time setup: Installing required dependencies...');
  console.log('   Dependencies: ' + REQUIRED_PACKAGES.join(', '));

  const pipArgs = ['-m', 'pip', 'install', '--quiet', ...REQUIRED_PACKAGES];
  const res = spawnSync(pythonCmd, pipArgs, { stdio: 'inherit' });

  if (res.status !== 0) {
    console.error('\n❌ [ERROR] Automatic dependency installation failed.');
    console.error(`   Please run manually: ${pythonCmd} -m pip install -r requirements.txt\n`);
    process.exit(1);
  }
  console.log('✅ [RASH-HIT Fractal Analysis] Dependencies installed successfully.\n');
}

function main() {
  const pythonCmd = findPythonCommand();
  if (!pythonCmd) {
    console.error('\n❌ [ERROR] Python 3.9+ was not found on your system.');
    console.error('   Please install Python from https://www.python.org/downloads/ and try again.\n');
    process.exit(1);
  }

  // Check if dependencies are installed; auto-install if missing
  const hasDeps = checkDependencies(pythonCmd);
  if (!hasDeps) {
    installDependencies(pythonCmd);
  }

  const scriptPath = path.resolve(__dirname, '..', 'run_analysis.py');
  const srcPath = path.resolve(__dirname, '..', 'src');
  const userArgs = process.argv.slice(2);

  // src/ layout: Python child process'e PYTHONPATH ile kök + src ver.
  const env = { ...process.env };
  const pathSep = process.platform === 'win32' ? ';' : ':';
  env.PYTHONPATH = [
    path.resolve(__dirname, '..'),
    srcPath,
    env.PYTHONPATH || '',
  ].filter(Boolean).join(pathSep);

  const child = spawn(pythonCmd, [scriptPath, ...userArgs], {
    stdio: 'inherit',
    cwd: process.cwd(),
    env,
  });

  child.on('error', (err) => {
    console.error(`\n❌ [ERROR] Failed to start analysis engine: ${err.message}\n`);
    process.exit(1);
  });

  child.on('close', (code) => {
    process.exit(code ?? 0);
  });
}

main();
