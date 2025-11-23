// static/js/quiz_client.js
// Mode-aware quiz client (adaptive shows "Time Spent" counting up; other modes keep countdown)

let MODE = null;
let ATTEMPT_ID = null;
let STATE = { current_diff: 3, seen_qids: [] };
let CURRENT_Q = null;
let TIME_LEFT = null;      // null means no per-question countdown (used by adaptive)
let TIMER_INT = null;
let GLOBAL_TIMER_INT = null;
let ELAPSE_INT = null;     // interval for elapsed timer in adaptive
let SCORE = 0;
let QUESTION_START_TS = null; // milliseconds epoch when question was shown

///////////// Helpers /////////////
const qs = id => document.getElementById(id);
const safeJson = async res => {
  const txt = await res.text();
  try { return JSON.parse(txt); } catch { return { error: txt || 'Invalid JSON' }; }
};
const nowMs = () => Date.now();

///////////// Sidebar helpers (if present) /////////////
function hideSidebar() {
  try {
    const sb = document.getElementById("sidebar");
    if (sb) sb.style.display = "none";
    const main = document.querySelector("main");
    if (main) main.style.marginLeft = "0";
  } catch (e) { console.error(e); }
}
function showSidebar() {
  try {
    const sb = document.getElementById("sidebar");
    if (sb) sb.style.display = "";
    const main = document.querySelector("main");
    if (main) main.style.marginLeft = "";
  } catch (e) { console.error(e); }
}

///////////// Mode selection & start /////////////
function chooseMode(mode) {
  MODE = mode;
  if (qs("modeName")) qs("modeName").innerText = mode;
  if (qs("modeSelect")) qs("modeSelect").style.display = "none";
  if (qs("gameArea")) qs("gameArea").style.display = "block";

  // hide sidebar on run start
  hideSidebar();

  if (mode === "minuterush") {
    const sec = prompt("Enter total time in seconds (e.g., 180 for 3 minutes):", "180");
    const s = Number.parseInt(sec, 10);
    STATE.time_left_total = Number.isFinite(s) && s > 0 ? s : 180;
    STATE.minute_rush_end = Date.now() + STATE.time_left_total * 1000;
  }

  // Create attempt on server
  fetchJson("/quiz/api/start_attempt", { mode: MODE, params: {} })
    .then(data => {
      if (data?.error) throw new Error(data.error || "Start attempt failed");
      ATTEMPT_ID = data.attempt_id;
      SCORE = 0;
      if (qs("score")) qs("score").innerText = SCORE;
      nextQuestion(null);
      if (MODE === "minuterush") startGlobalMinuteTimer();
    })
    .catch(err => {
      console.error(err);
      alert(err.message || "Could not start attempt");
      // restore sidebar on failure
      showSidebar();
    });
}

///////////// Global minute timer (minute_rush) /////////////
function startGlobalMinuteTimer() {
  if (GLOBAL_TIMER_INT) clearInterval(GLOBAL_TIMER_INT);
  updateGlobalMinuteTimer();
  GLOBAL_TIMER_INT = setInterval(updateGlobalMinuteTimer, 500);
}
function stopGlobalMinuteTimer() {
  if (GLOBAL_TIMER_INT) {
    clearInterval(GLOBAL_TIMER_INT);
    GLOBAL_TIMER_INT = null;
  }
}
function updateGlobalMinuteTimer() {
  if (!STATE || !STATE.minute_rush_end) return;
  const msLeft = STATE.minute_rush_end - Date.now();
  const secs = Math.max(0, Math.ceil(msLeft / 1000));
  if (qs("timeLeft")) qs("timeLeft").innerText = secs;
  if (msLeft <= 0) {
    stopGlobalMinuteTimer();
    finishRun();
  }
}

///////////// Fetch helper /////////////
async function fetchJson(url, body) {
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    if (!res.ok) {
      const json = await safeJson(res);
      throw new Error(json.error || `HTTP ${res.status}`);
    }
    return await res.json();
  } catch (err) {
    console.error("fetchJson error:", err);
    throw err;
  }
}

///////////// Question flow /////////////
function nextQuestion(lastOutcome) {
  // stop per-question timer if running (for non-adaptive modes)
  stopPerQuestionTimers();

  if (!ATTEMPT_ID) {
    alert("Attempt not started.");
    return;
  }

  const body = {
    mode: MODE,
    attempt_id: ATTEMPT_ID,
    last_outcome: lastOutcome,
    state: STATE
  };

  fetchJson("/quiz/api/get_question", body)
    .then(data => {

      // server error
      if (data?.error) {
        alert(data.error || "No questions available");
        finishRun();
        return;
      }

      // server signalled finished (no unseen questions)
      if (data?.finished) {
        flashMessage("All questions completed!", "green");
        // show sidebar before finishing
        showSidebar();
        finishRun();
        return;
      }

      // got a normal question
      CURRENT_Q = data;

      // merge server state safely (coerce seen ids to ints)
      if (data.state) {
        STATE.current_diff = typeof data.state.current_diff !== "undefined" ? data.state.current_diff : STATE.current_diff;
        if (Array.isArray(data.state.seen_qids)) {
          STATE.seen_qids = data.state.seen_qids.map(x => {
            try { return parseInt(x); } catch(e) { return x; }
          }).filter(x => x !== null && typeof x !== 'undefined');
        }
      }

      // push current q id to seen to avoid repetition
      if (CURRENT_Q?.id) {
        const qidNum = parseInt(CURRENT_Q.id);
        if (!STATE.seen_qids.includes(qidNum)) STATE.seen_qids.push(qidNum);
      }

      renderQuestion(data);

      // set a per-question timer ONLY for non-adaptive modes
      if (MODE === "challenger") {
        TIME_LEFT = Math.max(8, 20 - STATE.current_diff);
        startTimer();
      } else if (MODE === "minuterush" || MODE === "firststrike") {
        TIME_LEFT = 12;
        startTimer();
      } else {
        // adaptive has NO enforced per-question timer
        TIME_LEFT = null;
        // start elapsed timer for adaptive UI
        startElapsedTimer();
      }

    })
    .catch(err => {
      console.error("nextQuestion error:", err);
      alert("Problem fetching question.");
      showSidebar();
      finishRun();
    });
}

function renderQuestion(q) {
  const qEl = qs("question");
  if (qEl) qEl.innerText = q.prompt || "No prompt";

  // show difficulty neatly
  const diffEl = qs("qDifficulty");
  if (diffEl) diffEl.innerText = (q.difficulty !== undefined ? `Difficulty: ${q.difficulty}` : "");

  const optsDiv = qs("options");
  if (!optsDiv) return;
  optsDiv.innerHTML = "";

  (q.options || []).forEach(o => {
    const el = document.createElement("div");
    el.className = "option-card p-3 bg-white rounded shadow cursor-pointer";
    el.innerText = o.text ?? "Option";
    el.tabIndex = 0;
    el.role = "button";
    el.onclick = () => submitAnswer([o.id]);
    el.onkeydown = e => { if (e.key === "Enter" || e.key === " ") submitAnswer([o.id]); };
    optsDiv.appendChild(el);
  });

  // record question start timestamp for time_used calculation (in milliseconds)
  QUESTION_START_TS = nowMs();

  // update timer label based on mode
  const labelEl = qs("timeLabel");
  if (labelEl) {
    if (MODE === "adaptive") labelEl.innerText = "Time Spent:";
    else labelEl.innerText = "Time left:";
  }

  // clear any leftover elapsed ticker (defensive)
  if (ELAPSE_INT) {
    clearInterval(ELAPSE_INT);
    ELAPSE_INT = null;
  }
}

///////////// Per-question timers /////////////
function startTimer() {
  // If no per-question timer is set (adaptive), do nothing.
  if (TIME_LEFT === null || typeof TIME_LEFT === "undefined") return;

  // clear any elapsed timer
  stopElapsedTimer();

  if (TIMER_INT) clearInterval(TIMER_INT);
  const tl = qs("timeLeft");
  if (tl) tl.innerText = TIME_LEFT;
  TIMER_INT = setInterval(() => {
    TIME_LEFT--;
    const el = qs("timeLeft");
    if (el) el.innerText = Math.max(0, TIME_LEFT);
    if (TIME_LEFT <= 0) {
      clearInterval(TIMER_INT);
      TIMER_INT = null;
      submitAnswer([]); // time up -> submit empty selection
    }
  }, 1000);
}

function stopPerQuestionTimers() {
  if (TIMER_INT) { clearInterval(TIMER_INT); TIMER_INT = null; }
  stopElapsedTimer();
}

// Elapsed timer used by adaptive mode (shows time spent counting up)
function startElapsedTimer() {
  // Ensure any countdown is cleared
  if (TIMER_INT) { clearInterval(TIMER_INT); TIMER_INT = null; }
  // Start interval to update elapsed seconds
  stopElapsedTimer();
  updateElapsedDisplay(); // immediate first paint
  ELAPSE_INT = setInterval(updateElapsedDisplay, 250);
}

function stopElapsedTimer() {
  if (ELAPSE_INT) { clearInterval(ELAPSE_INT); ELAPSE_INT = null; }
}

// compute & write elapsed seconds to #timeLeft
function updateElapsedDisplay() {
  const tl = qs("timeLeft");
  if (!tl) return;
  if (!QUESTION_START_TS) {
    tl.innerText = "0";
    return;
  }
  const elapsedMs = nowMs() - QUESTION_START_TS;
  const elapsedSec = (elapsedMs / 1000);
  // show with 2 decimal places if <10s, else integer seconds
  if (elapsedSec < 10) tl.innerText = (Math.round(elapsedSec * 100) / 100).toFixed(2);
  else tl.innerText = Math.round(elapsedSec).toString();
}

///////////// Submit answer /////////////
function submitAnswer(selected) {
  // stop per-question timer(s)
  stopPerQuestionTimers();

  if (!ATTEMPT_ID || !CURRENT_Q) {
    console.warn("submitAnswer called with no attempt or no current question");
    return;
  }

  // compute time_used in seconds (float) even if user takes long time
  let time_used = null;
  if (QUESTION_START_TS) {
    const diff_ms = nowMs() - QUESTION_START_TS;
    time_used = Math.round((diff_ms / 1000) * 100) / 100; // two decimals
  }

  const body = {
    attempt_id: ATTEMPT_ID,
    question_id: CURRENT_Q.id,
    selected: selected,
    mode: MODE,
    time_used: time_used,
    state: STATE
  };

  fetchJson("/quiz/api/submit_answer", body)
    .then(resp => {
      if (resp?.error) {
        alert(resp.error || "Error submitting answer");
        return;
      }

      // update score
      SCORE = resp.attempt_score ?? SCORE;
      if (qs("score")) qs("score").innerText = SCORE;

      const correct = !!resp.correct;
      if (correct) flashMessage("Correct!", "green");
      else flashMessage("Wrong! Correct: " + (resp.correct_answers || []).join(", "), "red");

      // mode-specific termination: firststrike or challenger may end on wrong
      if ((MODE === "firststrike" || MODE === "challenger") && !correct) {
        // show sidebar then finish
        showSidebar();
        finishRun();
        return;
      }

      // adapt difficulty if server suggested
      if (resp.adjustment?.next_diff) STATE.current_diff = resp.adjustment.next_diff;

      // small delay for feedback then next question
      setTimeout(() => {
        nextQuestion({ correct, qid: CURRENT_Q.id, difficulty: CURRENT_Q.difficulty });
      }, 450);
    })
    .catch(err => {
      console.error("submitAnswer error:", err);
      alert("Network or server error while submitting answer.");
    });
}

function flashMessage(text, color) {
  const toast = document.createElement("div");
  toast.innerText = text;
  toast.style.position = "fixed";
  toast.style.right = "18px";
  toast.style.top = "18px";
  toast.style.padding = "10px 14px";
  toast.style.borderRadius = "8px";
  toast.style.background = color === "green" ? "#10b981" : "#ef4444";
  toast.style.color = "#fff";
  toast.style.zIndex = 2000;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 1200);
}

///////////// Ending the run /////////////
function finishRun() {
  stopPerQuestionTimers();
  stopGlobalMinuteTimer();

  // show sidebar again for smooth UX
  showSidebar();

  if (!ATTEMPT_ID) {
    window.location.href = "/quiz";
    return;
  }

  fetchJson("/quiz/api/end_attempt", { attempt_id: ATTEMPT_ID })
    .then(data => {
      if (data?.ok) {
        window.location.href = "/quiz/results/" + data.attempt_id;
      } else {
        alert("Could not finish attempt.");
      }
    })
    .catch(err => {
      console.error("finishRun error:", err);
      alert("Network error finishing attempt.");
    });
}

function endRun() {
  // user-triggered end
  showSidebar();
  finishRun();
}

// Auto-start if server rendered the page with a mode
document.addEventListener("DOMContentLoaded", function () {
  try {
    if (typeof window.SERVER_MODE !== "undefined" && window.SERVER_MODE) {
      setTimeout(() => chooseMode(window.SERVER_MODE), 50);
    }
  } catch (e) {
    console.error("Auto-start error", e);
  }
});
