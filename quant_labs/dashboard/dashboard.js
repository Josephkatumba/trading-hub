(()=>{
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const n=x=>x==null?'—':Number(x).toFixed(3);const money=x=>x==null?'':x<0?'negative':'positive';
let data,view='research',lab='all';
const $=id=>document.getElementById(id);
function empty(title,text,icon='◇'){return `<div class="empty"><div class="empty-icon">${icon}</div><h3>${esc(title)}</h3><p>${esc(text)}</p></div>`;}
function table(head,rows){return `<div class="table-wrap"><table><thead><tr>${head.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;}
function results(){
 const target=$('results');if(view==='qualified'){target.innerHTML=empty('No strategies qualified','Prospective evidence, independent review and CEO approval are required. Research results do not grant production permissions.');return;}
 if(view==='prior'){
  const prior=data.strategies.filter(s=>(lab==='all'||s.lab===lab)&&s.body.prior_research);
  if(!prior.length){target.innerHTML=empty('No prior research imported','This laboratory is ready for its own independent research.');return;}
  target.innerHTML='<p class="prior-note">Prior Codex results are preserved for context. They have not been re-evaluated under the shared standard and are excluded from the common leaderboard.</p>'+table(['LAB / STRATEGY','VERSION','PRIOR EVIDENCE','QUALIFICATION'],prior.map(s=>`<tr><td>${esc(s.lab)} / ${esc(s.id)}</td><td>${esc(s.version)}</td><td>Historical · ${s.body.prior_research.market_results.filter(r=>r.status!=='UNSUPPORTED').length} market cases</td><td><span class="badge">Not qualified</span></td></tr>`));return;
 }
 const rows=data.research_leaderboard.filter(r=>lab==='all'||r.lab===lab);
 target.innerHTML=rows.length?table(['LAB / STRATEGY','TEST N','NET E[R]','STRESS E[R]','HOLM p','REVIEW'],rows.map(r=>`<tr><td>${esc(r.lab)} / ${esc(r.strategy)}</td><td>${r.metrics.resolved}</td><td class="${money(r.metrics.net_expectancy_r)}">${n(r.metrics.net_expectancy_r)}</td><td>${n(r.stress.net_expectancy_r)}</td><td>${n(r.holm_p)}</td><td><span class="badge">Independent review required</span></td></tr>`)):empty('Awaiting shared evaluation','No research submission has completed the frozen evaluation and review process. Infrastructure checks do not count as strategy evidence.');
}
function render(d){data=d;const totals=d.labs.reduce((a,l)=>({strategies:a.strategies+l.strategies,active:a.active+l.active_experiments,rejected:a.rejected+l.rejected_experiments}),{strategies:0,active:0,rejected:0});
 $('summary').innerHTML=[['Independent laboratories',3,'Separate strategy ownership'],['Registered versions',totals.strategies,'Prior research retains its provenance'],['Active experiments',totals.active,'One bounded worker at a time'],['Qualified strategies',d.qualified_leaderboard.length,'No automatic promotions']].map(([title,value,note])=>`<div class="stat"><span>${esc(title)}</span><strong>${value}</strong><small>${esc(note)}</small></div>`).join('');
 const accents={codex:'#8ba6ef',claude:'#d0a18b',kimi:'#72bbae'};
 $('labs').innerHTML=d.labs.map(l=>`<article class="lab" style="--accent:${accents[l.id]}"><div class="lab-top"><span class="lab-icon">${l.id==='codex'?'CX':l.id==='claude'?'CL':'KI'}</span><div><h3>${esc(l.name)}</h3><small>${l.strategies?'Registered research provenance':'Ready for independent research'}</small></div></div><div class="lab-numbers"><div><b>${l.strategies}</b><span>Versions</span></div><div><b>${l.active_experiments}</b><span>Active</span></div><div><b>${l.rejected_experiments}</b><span>Rejected</span></div></div><div class="lab-state"><span>● Workspace isolated</span><span>Forward test: not started</span></div></article>`).join('');
 $('queue-status').textContent=d.settings.paused?'Queue paused':'Queue ready';
 $('queue').innerHTML=d.jobs.length?table(['LAB / STRATEGY','STATE','SEGMENTS','UPDATED'],d.jobs.slice(0,6).map(j=>`<tr><td>${esc(j.lab)} / ${esc(j.strategy)}</td><td><span class="badge">${esc(j.state)}</span></td><td>${j.segments}</td><td>${esc(j.updated.slice(11,19))} UTC</td></tr>`)):empty('Queue is clear','Labs can submit independent, versioned experiments for controlled evaluation.','◷');
 const segments=d.resources.map(r=>r.resources||{});const peak=Math.max(0,...segments.map(r=>r.peak_committed_mb||0));const elapsed=segments.reduce((a,r)=>a+(r.wall_seconds||0),0);
 $('resource-detail').innerHTML=`<div><span>Completed worker segments</span><b>${segments.length}</b></div><div><span>Recorded peak commit</span><b>${peak?peak.toFixed(1)+' MiB':'Not measured'}</b></div><div><span>Recorded evaluation time</span><b>${elapsed.toFixed(1)}s</b></div><div><span>Wall timeout per segment</span><b>30s default · 45s max</b></div>`;
 $('dataset-id').textContent='Dataset '+d.settings.dataset.slice(0,16)+'…';$('evaluator-id').textContent='Evaluator '+d.settings.evaluator.slice(0,16)+'…';$('updated').textContent='Snapshot '+new Date(d.generated_at).toLocaleString('en-GB',{timeZone:'Africa/Nairobi'})+' EAT';results();
}
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>{view=button.dataset.view;document.querySelectorAll('[data-view]').forEach(b=>{b.classList.toggle('active',b===button);b.setAttribute('aria-selected',String(b===button));});results();}));$('lab-filter').addEventListener('change',event=>{lab=event.target.value;results();});
const embedded=JSON.parse($('research-data').textContent);if(embedded)render(embedded);else fetch('/api/research').then(r=>{if(!r.ok)throw Error('snapshot unavailable');return r.json();}).then(render).catch(()=>{$('results').innerHTML=empty('Research snapshot unavailable','Start the isolated local preview or open the exported dashboard.');});
})();
