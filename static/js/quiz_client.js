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

///////////// Sidebar helpers (Flexbox compatible) /////////////
function hideSidebar() {
  try {
    const sb = document.getElementById("sidebar");
    if (sb) {
        sb.style.display = "none"; // Flexbox will auto-expand the main content
    }
  } catch (e) { console.error(e); }
}

function showSidebar() {
  try {
    const sb = document.getElementById("sidebar");
    if (sb) {
        sb.style.display = ""; // Restore default (flex) display
    }
  } catch (e) { console.error(e); }
}

///////////// Custom Modal for Minute Rush /////////////
function askForTime(callback) {
    const backdrop = document.createElement('div');
    Object.assign(backdrop.style, {
        position: 'fixed', top: 0, left: 0, width: '100%', height: '100%',
        background: 'rgba(15, 23, 42, 0.8)', backdropFilter: 'blur(8px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 3000,
        opacity: 0, transition: 'opacity 0.3s ease'
    });

    const modal = document.createElement('div');
    modal.className = 'bg-slate-800 border border-white/10 p-6 rounded-2xl shadow-2xl max-w-xs w-full space-y-4 transform scale-95 transition-all duration-300';
    modal.innerHTML = `
        <div class="text-center">
            <div class="w-12 h-12 bg-emerald-500/20 text-emerald-400 rounded-full flex items-center justify-center mx-auto mb-3">
                <i data-lucide="timer" class="w-6 h-6"></i>
            </div>
            <h3 class="text-xl font-bold text-white font-game">Time Limit</h3>
            <p class="text-slate-400 text-xs mt-1">Set duration in seconds</p>
        </div>
        <input type="number" value="180" id="mr-input" min="30" max="3600" class="w-full bg-slate-900 border border-slate-700 text-white px-4 py-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500 font-mono text-center text-lg font-bold">
        <button id="mr-btn" class="w-full bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white py-3 rounded-xl font-bold shadow-lg shadow-emerald-900/20 transition-all hover:scale-105 active:scale-95">
            Start Run
        </button>
    `;

    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);
    
    // Initialize icons
    if(window.lucide) window.lucide.createIcons();

    // Animate in
    requestAnimationFrame(() => {
        backdrop.style.opacity = '1';
        modal.style.transform = 'scale(1)';
    });

    const btn = modal.querySelector('#mr-btn');
    const input = modal.querySelector('#mr-input');
    
    input.focus();
    input.select();

    const submit = () => {
        const val = parseInt(input.value, 10);
        backdrop.style.opacity = '0';
        setTimeout(() => backdrop.remove(), 300);
        callback(val);
    };

    btn.onclick = submit;
    input.onkeydown = (e) => { if(e.key === 'Enter') submit(); };
}

///////////// Mode selection & start /////////////
function chooseMode(mode) {
  MODE = mode;
  
  if (mode === "minuterush") {
    askForTime((seconds) => {
        const s = Number.isFinite(seconds) && seconds > 0 ? seconds : 180;
        STATE.time_left_total = s;
        STATE.minute_rush_end = Date.now() + STATE.time_left_total * 1000;
        initGameUI();
        startAttempt();
    });
  } else {
      initGameUI();
      startAttempt();
  }
}

function initGameUI() {
  if (qs("modeName")) qs("modeName").innerText = MODE;
  if (qs("modeSelect")) qs("modeSelect").style.display = "none";
  if (qs("gameArea")) qs("gameArea").style.display = "block";
  
  // Re-trigger icon rendering for the newly visible game area
  if(window.lucide) window.lucide.createIcons();

  // hide sidebar on run start for immersive mode
  hideSidebar();
}

function startAttempt() {
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
      flashMessage(err.message || "Could not start attempt", "red");
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
    flashMessage("Attempt not started.", "red");
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
        flashMessage(data.error || "No questions available", "red");
        setTimeout(finishRun, 1500);
        return;
      }

      // server signalled finished (no unseen questions)
      if (data?.finished) {
        flashMessage("All questions completed!", "green");
        // show sidebar before finishing
        showSidebar();
        setTimeout(finishRun, 1000);
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
      flashMessage("Problem fetching question.", "red");
      showSidebar();
      setTimeout(finishRun, 1500);
    });
}

function renderQuestion(q) {
  const qEl = qs("question");
  if (qEl) qEl.innerText = q.prompt || "No prompt";

  // show difficulty neatly
  const diffEl = qs("qDifficulty");
  if (diffEl) diffEl.innerText = (q.difficulty !== undefined ? `Level ${q.difficulty}` : "XP Unknown");

  const optsDiv = qs("options");
  if (!optsDiv) return;
  optsDiv.innerHTML = "";

  (q.options || []).forEach(o => {
    // Generate <button> elements to match quiz.html CSS
    const el = document.createElement("button");
    // Classes here are illustrative; quiz.html CSS targets "#options button" specifically for the main look
    el.className = "option-btn transition-transform"; 
    
    // Inner HTML for a nice layout
    el.innerHTML = `
        <span class="pointer-events-none">${o.text ?? "Option"}</span>
        <i data-lucide="chevron-right" class="w-4 h-4 opacity-50 pointer-events-none"></i>
    `;
    
    el.onclick = () => submitAnswer([o.id]);
    // Accessibility
    el.tabIndex = 0;
    el.setAttribute('aria-label', o.text);
    
    optsDiv.appendChild(el);
  });
  
  // Initialize icons inside the new buttons
  if(window.lucide) window.lucide.createIcons();

  // record question start timestamp for time_used calculation (in milliseconds)
  QUESTION_START_TS = nowMs();

  // update timer label based on mode (if element exists)
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
        flashMessage(resp.error || "Error submitting answer", "red");
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
      flashMessage("Network or server error.", "red");
    });
}

function flashMessage(text, color) {
  const toast = document.createElement("div");
  
  // Content
  toast.innerHTML = `
    <div class="flex items-center gap-2">
        <span class="font-bold">${text}</span>
    </div>
  `;

  // Gamified Glassmorphism Styles
  toast.style.position = "fixed";
  toast.style.right = "24px";
  toast.style.top = "24px";
  toast.style.padding = "16px 24px";
  toast.style.borderRadius = "12px";
  toast.style.color = "#fff";
  toast.style.zIndex = 2000;
  toast.style.fontWeight = "600";
  toast.style.boxShadow = "0 10px 15px -3px rgba(0, 0, 0, 0.5)";
  toast.style.backdropFilter = "blur(12px)";
  toast.style.border = "1px solid rgba(255,255,255,0.1)";
  
  if (color === "green") {
      toast.style.background = "rgba(16, 185, 129, 0.9)"; // Emerald-500
      toast.style.borderLeft = "4px solid #34d399";
  } else {
      toast.style.background = "rgba(239, 68, 68, 0.9)"; // Red-500
      toast.style.borderLeft = "4px solid #f87171";
  }

  // Animation
  toast.style.transform = "translateX(100%)";
  toast.style.transition = "transform 0.3s cubic-bezier(0.16, 1, 0.3, 1)";
  
  document.body.appendChild(toast);
  
  // Trigger animation
  requestAnimationFrame(() => {
      toast.style.transform = "translateX(0)";
  });

  setTimeout(() => {
      toast.style.transform = "translateX(120%)";
      setTimeout(() => toast.remove(), 300);
  }, 1500);
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
        flashMessage("Could not finish attempt.", "red");
      }
    })
    .catch(err => {
      console.error("finishRun error:", err);
      flashMessage("Network error finishing attempt.", "red");
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