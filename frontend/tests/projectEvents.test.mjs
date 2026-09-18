import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const source = readFileSync(new URL("../src/api/projectEvents.ts", import.meta.url), "utf8");
const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

function setup() {
    const sockets = [];
    const timers = new Map();
    let nextTimer = 0;
    class FakeWebSocket {
        constructor(url) { this.url = url; sockets.push(this); }
        close() { this.onclose?.(); }
    }
    const exported = {};
    vm.runInNewContext(code, {
        exports: exported,
        require: () => ({ buildWebSocketUrl: (id) => `wss://example.test/ws?project_id=${id}` }),
        WebSocket: FakeWebSocket,
        setTimeout: (callback, delay) => {
            const id = ++nextTimer;
            timers.set(id, { callback, delay });
            return id;
        },
        clearTimeout: (id) => timers.delete(id),
    });
    const runTimer = () => {
        assert.equal(timers.size, 1);
        const [id, timer] = timers.entries().next().value;
        timers.delete(id);
        timer.callback();
        return timer.delay;
    };
    return { subscribe: exported.subscribeToProjectEvents, sockets, timers, runTimer };
}

test("reconnects and reconciles saved state after every successful upgrade", () => {
    const { subscribe, sockets, runTimer } = setup();
    let connected = 0;
    const messages = [];
    const stop = subscribe("project", (event) => messages.push(event.data), () => connected++);
    assert.equal(sockets[0].url, "wss://example.test/ws?project_id=project");
    sockets[0].onopen();
    sockets[0].onmessage({ data: "first" });
    sockets[0].close();
    runTimer();
    sockets[1].onopen();
    sockets[1].onmessage({ data: "second" });
    assert.equal(connected, 2);
    assert.deepEqual(messages, ["first", "second"]);
    stop();
});

test("caps backoff and resets it when the connection recovers", () => {
    const { subscribe, sockets, runTimer } = setup();
    const stop = subscribe("project", () => {}, () => {});
    for (let attempt = 0; attempt < 8; attempt++) {
        sockets.at(-1).close();
        const delay = runTimer();
        const expected = Math.min(30_000, 1_000 * 2 ** Math.min(attempt, 5));
        assert.ok(delay >= expected && delay < expected + 500);
    }
    sockets.at(-1).onopen();
    sockets.at(-1).close();
    assert.ok(runTimer() < 1500);
    stop();
});

test("unmount cancels reconnection and ignores late messages", () => {
    const { subscribe, sockets, timers } = setup();
    const stop = subscribe("project", () => assert.fail("late message"), () => assert.fail("late open"));
    sockets[0].close();
    assert.equal(timers.size, 1);
    stop();
    assert.equal(timers.size, 0);
    sockets[0].onmessage({ data: "late" });
    sockets[0].onopen();
    assert.equal(sockets.length, 1);
});
