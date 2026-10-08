"use strict";
let worker;
window.checkResult = null;
window.startCheck = function (payload) {
  worker = new Worker("worker.js");
  worker.onmessage = event => { window.checkResult = event.data; worker.terminate(); };
  worker.onerror = () => {
    window.checkResult = { exit_code: 1, output: "Среда проверки не запустилась.", no_tests: false };
    worker.terminate();
  };
  worker.postMessage(payload);
};
window.stopCheck = function () { if (worker) worker.terminate(); };
