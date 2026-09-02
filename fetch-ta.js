import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE_URL = process.env.TA_BASE_URL || 'https://example.com/c';
const OUTPUT_DIR = 'ta';
const AUDIO_DIR = path.join(OUTPUT_DIR, 'audio');
const START_PAGE = 1;
const DELAY_MS = 30000;

const limitArg = parseInt(process.argv[2], 10);
const END_PAGE = Number.isFinite(limitArg) ? limitArg : 200;

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function hasAudio(pageNumber) {
    const pattern = new RegExp(`^${pageNumber}(-\\d+)?\\.[a-z0-9]+$`, 'i');
    return fs.readdirSync(AUDIO_DIR).some(f => pattern.test(f));
}

function alreadyFetched(pageNumber) {
    return fs.existsSync(path.join(OUTPUT_DIR, `${pageNumber}.html`)) && hasAudio(pageNumber);
}

async function fetchPage(page, pageNumber) {
    const url = `${BASE_URL}/${pageNumber}`;
    console.log(`Fetching ${url}`);

    // The audio player streams via HTTP Range requests (206 Partial Content).
    // Chromium's devtools protocol doesn't reliably retain the body for those,
    // so we only use the 'response' event to learn the URL, then download it
    // ourselves with a plain, independent HTTP request below.
    const audioUrls = new Set();
    const onResponse = (response) => {
        if (response.request().resourceType() === 'media' || /\.mp3(\?|$)/i.test(response.url())) {
            audioUrls.add(response.url());
        }
    };
    page.on('response', onResponse);

    await page.goto(url, { waitUntil: 'load', timeout: 60000 });
    await page.waitForTimeout(5000);

    page.off('response', onResponse);

    const html = await page.content();
    fs.writeFileSync(path.join(OUTPUT_DIR, `${pageNumber}.html`), html);
    console.log(`Saved: ${OUTPUT_DIR}/${pageNumber}.html`);

    const urls = [...audioUrls];
    for (let i = 0; i < urls.length; i++) {
        const audioUrl = urls[i];
        const res = await page.context().request.get(audioUrl);
        if (!res.ok()) {
            throw new Error(`audio download failed (${res.status()}): ${audioUrl}`);
        }
        const buffer = await res.body();
        const ext = path.extname(new URL(audioUrl).pathname) || '.mp3';
        const suffix = urls.length > 1 ? `-${i + 1}` : '';
        const audioFileName = path.join(AUDIO_DIR, `${pageNumber}${suffix}${ext}`);
        fs.writeFileSync(audioFileName, buffer);
        console.log(`Saved audio: ${audioFileName}`);
    }

    if (urls.length === 0) {
        console.warn(`No audio found on page ${pageNumber}`);
    }
}

async function main() {
    if (!fs.existsSync(OUTPUT_DIR)) {
        fs.mkdirSync(OUTPUT_DIR, { recursive: true });
        console.log(`Created directory: ${OUTPUT_DIR}`);
    }
    if (!fs.existsSync(AUDIO_DIR)) {
        fs.mkdirSync(AUDIO_DIR, { recursive: true });
        console.log(`Created directory: ${AUDIO_DIR}`);
    }

    const browser = await chromium.launch();

    const failedPages = [];
    try {
        for (let pageNumber = START_PAGE; pageNumber <= END_PAGE; pageNumber++) {
            if (alreadyFetched(pageNumber)) {
                console.log(`Skipping page ${pageNumber} (already have html + audio)`);
                continue;
            }

            // Fresh tab per page: a single long-lived tab accumulated enough
            // state over ~70+ navigations to make audio capture flaky.
            const page = await browser.newPage();
            try {
                await fetchPage(page, pageNumber);
            } catch (error) {
                console.error(`ERROR fetching page ${pageNumber}: ${error.message}`);
                failedPages.push(pageNumber);
            } finally {
                await page.close();
            }

            if (pageNumber < END_PAGE) {
                await sleep(DELAY_MS);
            }
        }
    } finally {
        await browser.close();
    }

    if (failedPages.length > 0) {
        console.log(`DONE with errors: failed pages [${failedPages.join(', ')}]`);
    } else {
        console.log(`DONE: fetched pages ${START_PAGE}-${END_PAGE} successfully`);
    }
}

process.on('unhandledRejection', (error) => {
    console.error(`FATAL unhandled rejection: ${error && error.stack ? error.stack : error}`);
    process.exit(1);
});

main().catch((error) => {
    console.error(`FATAL: ${error && error.stack ? error.stack : error}`);
    process.exit(1);
});
