// Opens an app or an empty graph, runs MCP tool calls in order and exports the result.
const job = () => cy.readFile(Cypress.expose('jobFile'));
const ctl = (fn) => cy.window().its('testController', { timeout: 90000 }).then({ timeout: 180000 }, fn);
const AsyncFunction = (async () => {}).constructor;
Cypress.on('uncaught:exception', () => false);

it('run ops', () => {
  job().then((j) => {
    cy.viewport(1440, 900);
    cy.visit(`${Cypress.expose('base')}/?new=true`, { timeout: 120000 });
    cy.wait(2500);
    if (j.from) {
      cy.readFile(j.from, 'utf8').then({ timeout: 90000 }, (raw) => {
        const text = typeof raw === 'string' ? raw.trim() : JSON.stringify(raw);
        return ctl((c) => c.loadStringifiedGraph(text));
      });
      cy.wait(j.loadWait ?? 3000);
    }
    const results = [];
    ctl((c) => c.beginAIAgentTurn());
    (j.ops || []).forEach((op, index) => {
      ctl(async (c) => {
        if (results.some((r) => r.is_error)) return;
        const r = await c.callMCPTool(op.tool, op.input ?? {});
        const images = r.images ?? [];
        results.push({ index, tool: op.tool, input: op.input, is_error: !!r.is_error, content: r.content, images });
      });
    });
    ctl((c) => c.finishAIAgentTurn());
    if (j.after) ctl((c) => new AsyncFunction('c', j.after)(c));
    cy.wait(j.settle ?? 2000);
    ctl((c) => ({
      graph: JSON.parse(JSON.stringify(c.getGraph().getSerializedStoredGraph())),
      problems: c.callMCPTool('inspect_warnings_and_errors', {}),
    })).then((x) => {
      cy.writeFile(`${j.out}/results.json`, results);
      if (j.extra) ctl((c) => new AsyncFunction('c', j.extra)(c)).then((e) => cy.writeFile(`${j.out}/extra.json`, e ?? null));
      cy.writeFile(`${j.out}/export.json`, x.graph);
      cy.writeFile(`${j.out}/problems.json`, x.problems);
    });
    if (j.shot) {
      cy.wait(1000);
      cy.screenshot(j.shot, { capture: 'viewport', overwrite: true });
    }
  });
});
