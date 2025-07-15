#!/usr/bin/env node

const fs = require('fs');
const path = require('path');

if (process.argv.length < 3) {
    console.error('Usage: node split-file.js <filename>');
    process.exit(1);
}

const filename = process.argv[2];

if (!fs.existsSync(filename)) {
    console.error(`File ${filename} does not exist`);
    process.exit(1);
}

const content = fs.readFileSync(filename, 'utf8');
const parts = content.split('===');
const inputDir = path.dirname(filename);

parts.forEach((part, index) => {
    const trimmedPart = part.trim();
    if (trimmedPart) {
        const outputFilename = path.join(inputDir, `${index + 1}.md`);
        fs.writeFileSync(outputFilename, trimmedPart);
        console.log(`Created: ${outputFilename}`);
    }
});

console.log(`Split ${filename} into ${parts.filter(p => p.trim()).length} parts`);