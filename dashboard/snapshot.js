const puppeteer = require('puppeteer');

(async () => {
    console.log("Launching headless browser...");
    const browser = await puppeteer.launch({ args: ['--no-sandbox'] });
    const page = await browser.newPage();
    
    // Set a good desktop viewport
    await page.setViewport({ width: 1400, height: 900 });
    
    console.log("Navigating to dashboard...");
    await page.goto('http://localhost:8080');
    
    // Wait for the JS to fetch the incidents from the API
    console.log("Waiting for network idle...");
    await new Promise(r => setTimeout(r, 4000)); // hard wait to ensure animations and fetch complete
    
    console.log("Taking screenshot...");
    await page.screenshot({ path: 'dashboard-preview.png' });
    
    await browser.close();
    console.log("Done! Screenshot saved to dashboard-preview.png");
})();
