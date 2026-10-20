"""Minimal local reviewer UI. No external dependencies; not a model implementation.

Run:  python review_ui.py        (then open http://127.0.0.1:8765)

The reviewer can:
  * type an arbitrary question,
  * change eligible / visible plans and the selected plan between turns,
  * change the selected options between turns,
  * reset the conversation history,
  * see which mode is active (offline deterministic vs. live LLM),
  * see the automated guardrail result for each answer.

This is the same interface as the supplied scaffold, extended with a mode
badge, per-turn diagnostics and a reset that also clears referent memory.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coverage_assistant import CoverageAssistant  # noqa: E402
from coverage_assistant.catalog import Catalog  # noqa: E402

CATALOG = Catalog.load()
PLANS = CATALOG.plans
HOST = "127.0.0.1"
PORT = int(os.environ.get("REVIEW_UI_PORT", "8765"))
MODE = os.environ.get("ASSISTANT_MODE", "offline").lower()

HTML = r"""<!doctype html><meta charset='utf-8'><title>Independent AI assessment test</title>
<style>body{font:16px system-ui;max-width:900px;margin:30px auto;padding:0 14px}fieldset{margin:12px 0;padding:12px}label{margin:8px}button{padding:9px;margin:5px}textarea{width:100%;min-height:70px}.log{padding:10px;background:#f5f5f5;min-height:160px;white-space:pre-wrap;white-space:pre-wrap;font-family:ui-monospace,monospace}small{color:#555}
.badge{display:inline-block;padding:4px 10px;border-radius:12px;font-size:13px;font-weight:600}
.badge.offline{background:#fde68a;color:#7c2d12}.badge.live{background:#bbf7d0;color:#14532d}
.planrow{margin:2px 0}.warn{color:#b45309}</style>
<h2>AI Coverage Assistant &mdash; Local Reviewer Harness</h2>
<p><span id='mode' class='badge'></span> <small id='model'></small></p>
<fieldset><legend>State</legend><div id='plans'></div><label>Selected plan <select id='selected'></select></label><label>Selected options (comma-separated IDs: electronics_plus, exhaust_plus) <input id='opts' placeholder='e.g. electronics_plus'></label><button onclick='resetChat()'>Reset conversation</button></fieldset>
<div id='log' class='log'></div><p><textarea id='q' placeholder='Type a new question'></textarea></p><button onclick='ask()'>Ask</button>
<script>
const plans=__PLANS__;
let log=document.getElementById('log');
let sel=document.getElementById('selected');
document.getElementById('mode').textContent=__MODE__;
document.getElementById('mode').className='badge '+(__LIVE__?'live':'offline');
document.getElementById('model').textContent=__MODEL__;
plans.forEach(p=>{let id=p.id; let el=document.createElement('div');el.className='planrow';el.innerHTML=`<label><input type="checkbox" data-kind="eligible" value="${id}" checked> Eligible</label><label><input type="checkbox" data-kind="visible" value="${id}" checked> Visible</label> ${p.name} (${id})`;document.getElementById('plans').appendChild(el);let o=document.createElement('option');o.value=id;o.textContent=p.name;sel.appendChild(o)});
function vals(kind){return [...document.querySelectorAll(`input[data-kind="${kind}"]:checked`)].map(e=>e.value)}
async function ask(){let q=document.getElementById('q').value.trim();if(!q)return;
let state={eligible_ids:vals('eligible'),visible_ids:vals('visible'),selected_id:sel.value,selected_options:document.getElementById('opts').value.split(',').map(x=>x.trim()).filter(Boolean)};
let r=await fetch('/ask',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({question:q,state})});let data=await r.json();
let extra='';
if(data.guardrail){extra='\n  [intent='+data.guardrail.intent+', referent='+(data.guardrail.referent_plan_id||'none')+', allowed='+JSON.stringify(data.guardrail.allowed_plan_ids)+', guardrail='+(data.guardrail.ok?'PASS':'FAIL: '+data.guardrail.violations.join('; '))+']';}
log.textContent+=`
You: ${q}
Assistant: ${data.answer||data.error}${extra}
`;document.getElementById('q').value='';}
async function resetChat(){await fetch('/reset',{method:'POST'});log.textContent='Conversation reset.
';}
</script>"""


def build_html():
    return (
        HTML.replace("__PLANS__", json.dumps([{"id": p["id"], "name": p["name"]} for p in PLANS.values()]))
        .replace("__MODE__", json.dumps("LIVE LLM" if MODE == "live" else "OFFLINE_DETERMINISTIC - NOT AN LLM"))
        .replace("__LIVE__", "true" if MODE == "live" else "false")
        .replace("__MODEL__", json.dumps(os.environ.get("LLM_MODEL", "")))
        .replace(
            "__MODEL__",
            json.dumps(
                (STARTUP_ERROR or "")
                or os.environ.get("LLM_MODEL", "")
            ),
        )
    )


def make_assistant():
    """Build the assistant, degrading to a clear error state if live mode
    cannot start (for example, no API key configured).

    The UI must still load so the reviewer can see *why* it is not in live
    mode, rather than getting a stack trace.
    """
    try:
        return CoverageAssistant(mode=MODE), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


ASSISTANT, STARTUP_ERROR = make_assistant()


class Handler(BaseHTTPRequestHandler):
    assistant = ASSISTANT

    def _reply(self, obj, status=200):
        out = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, fmt, *args):  # quieter console
        pass

    def do_GET(self):
        if self.path != "/":
            self.send_error(404)
            return
        out = build_html().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/reset":
                Handler.assistant, error = make_assistant()
                return self._reply({"ok": True, "error": error})
            if self.path == "/state":
                return self._reply({"mode": Handler.assistant.mode_label})
            if self.path != "/ask":
                return self._reply({"error": "not found"}, 404)
            if Handler.assistant is None:
                return self._reply(
                    {
                        "error": (
                            "The assistant could not start in the requested mode: "
                            + (STARTUP_ERROR or "unknown error")
                            + " Set your API key and restart, or run without "
                            "ASSISTANT_MODE=live to use the offline mode."
                        )
                    },
                    503,
                )
            answer = Handler.assistant.answer(data["question"], data.get("state"))
            trace = Handler.assistant.last_trace
            payload = {"answer": answer, "mode": Handler.assistant.mode_label}
            if trace is not None:
                payload["guardrail"] = {
                    "intent": trace.intent,
                    "referent_plan_id": trace.referent_plan_id,
                    "referent_source": trace.referent_source,
                    "allowed_plan_ids": trace.allowed_plan_ids,
                    "ok": not trace.violations,
                    "violations": trace.violations,
                    "repaired": trace.repaired,
                    "fallback_used": trace.fallback_used,
                    "error": trace.error,
                }
            self._reply(payload)
        except Exception as exc:  # surface errors instead of a bare 500
            self._reply({"error": f"{type(exc).__name__}: {exc}"}, 400)


if __name__ == "__main__":
    print(f"Open http://{HOST}:{PORT} - local only")
    if ASSISTANT is None:
        print(f"Mode: live requested but could not start: {STARTUP_ERROR}")
        print("Set your API key and restart, or run without ASSISTANT_MODE=live.")
    else:
        print(f"Mode: {ASSISTANT.mode_label}")
    HTTPServer((HOST, PORT), Handler).serve_forever()
