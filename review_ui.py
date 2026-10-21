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
.badge.ok{background:#bbf7d0;color:#14532d}.badge.fail{background:#fecaca;color:#7f1d1d}
.log .pending{color:#666}
.planrow{margin:2px 0}.warn{color:#b45309}</style>
<h2>AI Coverage Assistant &mdash; Local Reviewer Harness</h2>
<p><span id='mode' class='badge'></span> <small id='model'></small></p>
<fieldset><legend>State</legend><div id='plans'></div><label>Selected plan <select id='selected'></select></label><label>Selected options (comma-separated IDs: electronics_plus, exhaust_plus) <input id='opts' placeholder='e.g. electronics_plus'></label><button onclick='resetChat()'>Reset conversation</button></fieldset>
<div id='log' class='log'></div><p><textarea id='q' placeholder='Type a new question'></textarea></p><button id='askBtn' onclick='ask()'>Ask</button>
<script>
const plans=__PLANS__;
var logEl=document.getElementById('log');
var selEl=document.getElementById('selected');
var qEl=document.getElementById('q');
var askBtn=document.getElementById('askBtn');
var optEl=document.getElementById('opts');
var modeEl=document.getElementById('mode');
var modelEl=document.getElementById('model');
modeEl.textContent=__MODE__;
modeEl.className='badge '+(__LIVE__?'live':'offline');
modelEl.textContent=__MODEL__;
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function appendEntry(kind, html){var d=document.createElement('div');d.className=kind;if(html!=null){d.innerHTML=html;}logEl.appendChild(d);logEl.scrollTop=logEl.scrollHeight;return d;}
var loadedOnce=false;
function boot(){if(loadedOnce)return;loadedOnce=true;
  var planRows=document.getElementById('plans');
  plans.forEach(function(p){
    var row=document.createElement('div');row.className='planrow';
    var lab1=document.createElement('label');lab1.style.margin='2px 6px 2px 0';
    var cb1=document.createElement('input');cb1.type='checkbox';cb1.setAttribute('data-kind','eligible');cb1.value=p.id;cb1.checked=true;cb1.style.margin='0 4px 0 0';
    lab1.appendChild(cb1);lab1.appendChild(document.createTextNode(' Eligible'));
    var lab2=document.createElement('label');lab2.style.margin='2px 6px 0 0';
    var cb2=document.createElement('input');cb2.type='checkbox';cb2.setAttribute('data-kind','visible');cb2.value=p.id;cb2.checked=true;cb2.style.margin='0 4px 0 0';
    lab2.appendChild(cb2);lab2.appendChild(document.createTextNode(' Visible'));
    var t=document.createElement('span');t.style.color='#444';t.style.fontWeight=400;t.textContent=p.name+' ('+p.id+')';
    row.appendChild(lab1);row.appendChild(lab2);row.appendChild(t);
    planRows.appendChild(row);
    var opt=document.createElement('option');opt.value=p.id;opt.textContent=p.name;selEl.appendChild(opt);
  });
  logEl.scrollTop=logEl.scrollHeight;
}
function vals(kind){var out=[];var bs=document.querySelectorAll('input[data-kind="'+kind+'"]:checked');for(var i=0;i<bs.length;i++){out.push(bs[i].value);}return out;}
function getSelectedOpts(){var v=optEl.value;return v.split(',').map(function(x){return x.trim();}).filter(function(x){return x.length;});}
async function ask(){var q=qEl.value.trim();if(!q)return;
  var pending=appendEntry('pending','You: '+esc(q)+'<br>Assistant: thinking&hellip;');
  askBtn.disabled=true;
  try{
    var state={eligible_ids:vals('eligible'),visible_ids:vals('visible'),selected_id:selEl.value,selected_options:getSelectedOpts()};
    var r=await fetch('/ask',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({question:q,state:state})});
    var data=await r.json();
    var extra='';
    if(data.guardrail){
      var g=data.guardrail;
      var st=g.status||(g.ok?'PASS':'FAIL');
      var cls=(st==='PASS'||st==='REPAIRED'||st==='FALLBACK')?'ok':'fail';
      var detail=[];
      if(g.rejected_draft_violations&&g.rejected_draft_violations.length){
        detail.push('rejected draft: '+esc(g.rejected_draft_violations.join('; ')));
      }
      if(g.violations&&g.violations.length){detail.push('delivered answer: '+esc(g.violations.join('; ')));}
      if(g.repaired){detail.push('repaired by a second model call');}
      if(g.fallback_used){detail.push('deterministic fallback used');}
      extra='<hr><small>[intent='+esc(g.intent)+', referent='+esc(g.referent_plan_id||'none')+'], allowed='+esc(JSON.stringify(g.allowed_plan_ids))+'] <span class="badge '+cls+'">'+esc(st)+'</span>'+(detail.length?'<br><small>'+detail.join('<br>')+'</small>':'');
    }
    pending.innerHTML='You: '+esc(q)+'<br>Assistant: '+esc(data.answer!=null?data.answer:(data.error||'[empty]'))+extra;
    qEl.value='';
  }catch(err){
    pending.innerHTML='You: '+esc(q)+'<br>Assistant: [request failed: '+esc(err)+']';
  }finally{
    askBtn.disabled=false;
  }
}
async function resetChat(){try{await fetch('/reset',{method:'POST'});}catch(err){}logEl.innerHTML='Conversation reset.';qEl.value='';askBtn.disabled=false;}
boot();
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
                # `ok` describes the answer the customer actually received, not
                # the first draft. A draft that was rejected and then repaired
                # or replaced must not be shown to the reviewer as a failure
                # of the delivered answer; the rejected draft is still listed
                # under `rejected_draft_violations`.
                delivered_ok = trace.final_ok
                if delivered_ok and trace.repaired:
                    status = "REPAIRED"
                elif delivered_ok and trace.fallback_used:
                    status = "FALLBACK"
                elif delivered_ok:
                    status = "PASS"
                else:
                    status = "FAIL"
                payload["guardrail"] = {
                    "intent": trace.intent,
                    "referent_plan_id": trace.referent_plan_id,
                    "referent_source": trace.referent_source,
                    "allowed_plan_ids": trace.allowed_plan_ids,
                    "ok": delivered_ok,
                    "status": status,
                    "violations": trace.final_violations,
                    "rejected_draft_violations": trace.violations,
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
