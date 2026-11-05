// Scratch Cypress config for the skill; the repo's own config is left alone.
const fs = require('fs');
const path = require('path');

const out = process.env.TM_OUT;

module.exports = {
  video: false,
  screenshotOnRunFailure: true,
  trashAssetsBeforeRuns: false,
  screenshotsFolder: path.join(out, 'shots'),
  e2e: {
    specPattern: path.join(__dirname, `${process.env.TM_SPEC}.cy.js`),
    supportFile: false,
    setupNodeEvents(on, config) {
      config.expose = { ...config.expose, jobFile: process.env.TM_JOB, base: process.env.TM_BASE_URL };
      // verify.cy.js defines one test per scenario, so it needs the job before the spec runs.
      if (process.env.TM_JOB_INLINE) config.expose.job = fs.readFileSync(process.env.TM_JOB_INLINE, 'utf8');
      on('before:browser:launch', (browser, options) => {
        if (browser.family === 'chromium') {
          // The window must be larger than the viewport or the WebGL canvas renders black.
          options.args.push('--use-gl=angle', '--use-angle=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist', '--window-size=1900,4300');
        }
        return options;
      });
      return config;
    },
    testIsolation: false,
    retries: 0,
  },
  defaultCommandTimeout: 60000,
  visibilityStrategy: 'legacy',
};
