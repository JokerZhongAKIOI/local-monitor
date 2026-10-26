const $ = s => document.querySelector(s);
const sites = {local: {name:'校园内网站点',host:'10.177.41.90',icon:'◎'},goj:{name:'GOJ 在线评测',host:'www.goj.wiki',icon:'G'}};
let real = {monitors:[],events:[]}, demo = sessionStorage.getItem('monitor-demo') !== 'off', filter = 'all', view = 'overview', synced = null;
const now = Date.now()/1000;
const sample = {monitors:[
{id:'demo-1',site:'local',target:'lin_chen',state:'online',ip:'10.177.42.128',checked:now-3,enabled:1},
{id:'demo-2',site:'goj',target:'akioi_2024',state:'online',ip:'203.0.113.24',checked:now-6,enabled:1},
{id:'demo-3',site:'goj',target:'summer_code',state:'offline',ip:null,checked:now-8,enabled:1},
{id:'demo-4',site:'local',target:'zhang_ming',state:'online',ip:'10.177.43.56',checked:now-4,enabled:1}
],events:[{site:'local',target:'lin_chen',kind:'change',message:'用户上线 · 10.177.42.128',time:now-120},{site:'goj',target:'akioi_2024',kind:'change',message:'IP 地址变更 · 203.0.113.24',time:now-360},{site:'goj',target:'summer_code',kind:'change',message:'用户已离线',time:now-840}]};
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const data = () => demo ? sample : real;
const status = m => !m.enabled ? 'paused' : m.state;
const labels = {online:'在线',offline:'离线',error:'异常',disconnected:'待连接',paused:'已暂停',session:'会话有效'};
function relative(t){if(!t)return '尚未检查';let n=Math.max(0,Math.floor(Date.now()/1000-t));return n<60?`${n} 秒前`:n<3600?`${Math.floor(n/60)} 分钟前`:n<86400?`${Math.floor(n/3600)} 小时前`:new Date(t*1000).toLocaleDateString('zh-CN');}
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').hidden=true,4000);}
async function api(path,body){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Monitor-Request':'1'},body:JSON.stringify(body)});const result=await response.json();if(!response.ok)throw Error(result.error||'请求失败');return result;}
function eventHTML(e){return `<div class="event"><span class="event-icon">${e.kind==='error'?'!':'↗'}</span><div class="event-body"><strong>${esc(e.target)} <span class="site-name">· ${esc(sites[e.site]?.name||e.site)}</span></strong><p>${esc(e.message)}</p></div><time>${relative(e.time)}</time></div>`;}
function render(){
 const d=data(), online=d.monitors.filter(m=>status(m)==='online').length, offline=d.monitors.filter(m=>status(m)==='offline').length, used=new Set(d.monitors.map(m=>m.site)).size;
 $('#demo-banner').hidden=!demo;$('#nav-count').textContent=d.monitors.length;$('#monitor-count').textContent=d.monitors.length;$('#all-count').textContent=d.monitors.length;
 const metrics=[['监控用户',d.monitors.length,'位用户正在你的关注之中','♙'],['当前在线',online,`<b>● 在线</b> · ${d.monitors.length?Math.round(online/d.monitors.length*100):0}% 的监控用户`,'↗'],['当前离线',offline,'等待下一次上线','◷'],['已连接站点',used,'共 2 个预置站点可接入','◎']];
 $('#stats').innerHTML=metrics.map(([title,num,note,icon])=>`<article class="stat"><div class="stat-head">${title}<span class="stat-icon">${icon}</span></div><div class="stat-number">${num.toString().padStart(2,'0')}</div><div class="stat-bottom">${note}</div></article>`).join('');
 const query=$('#search').value.toLowerCase(), rows=d.monitors.filter(m=>(filter==='all'||status(m)===filter)&&`${m.target} ${m.ip||''}`.toLowerCase().includes(query));
 $('#monitor-rows').innerHTML=rows.map(m=>`<tr><td><div class="user-cell"><span class="user-avatar ${esc(m.site)}">${esc(m.target.slice(0,1).toUpperCase())}</span><div><strong>${esc(m.target)}</strong><small>${demo?'演示用户':'授权监控'}</small></div></div></td><td><span class="site-mark">${sites[m.site].icon}</span><span class="site-name">${sites[m.site].name}</span></td><td><span class="badge ${status(m)}" title="${esc(m.error||'')}">${labels[status(m)]||'未知'}</span></td><td><span class="ip ${m.ip?'':'ip-empty'}">${esc(m.ip||'—')}</span></td><td class="time">${relative(m.checked)}${m.last_activity?`<small class="activity-time">会话活动：${esc(new Date(m.last_activity*1000).toLocaleString('zh-CN'))}</small>`:''}</td><td><div class="row-actions"><button data-action="copy" data-id="${m.id}" aria-label="复制 IP" title="复制 IP">⧉</button><button data-action="toggle" data-id="${m.id}" aria-label="${m.enabled?'暂停':'恢复'}监控" title="${m.enabled?'暂停':'恢复'}">${m.enabled?'Ⅱ':'▷'}</button><button data-action="delete" data-id="${m.id}" aria-label="删除监控" title="移除">×</button></div></td></tr>`).join('');
 $('#empty').hidden=rows.length>0;$('#empty h3').textContent=d.monitors.length?'没有匹配的监控':'从第一个监控开始';$('#row-summary').textContent=`共 ${d.monitors.length} 项监控 · 显示 ${rows.length} 项`;
 $('#site-mini').innerHTML=Object.entries(sites).map(([id,s])=>`<div class="mini-site"><span class="site-icon ${id}">${s.icon}</span><div class="site-detail"><strong>${s.name}</strong><small>${s.host}</small></div><span class="mini-count">${d.monitors.filter(m=>m.site===id).length} 个监控 <span class="dot"></span></span></div>`).join('');
 const events=d.events;$('#recent-events').innerHTML=events.slice(0,3).map(eventHTML).join('')||'<div class="no-events">暂无动态，添加监控后将在这里记录。</div>';
 $('#event-list').innerHTML=events.map(eventHTML).join('')||'<div class="no-events">暂无活动日志</div>';
 $('#site-cards').innerHTML=Object.entries(sites).map(([id,s])=>`<article class="site-card"><span class="site-icon ${id}">${s.icon}</span><h2>${s.name}</h2><p>${s.host}<br>${id==='local'?'需要在可访问该地址的内网环境中运行。':'支持本人账号活动会话 IP 与最后活动时间，不代表实时在线。'}<br>${id==='goj'?'适配协议：表单登录 + HTML 个人会话':'适配协议：JSON + Cookie 会话'}</p><span class="badge disconnected">${demo?'演示连接':'等待授权接入'}</span><br><button class="primary" data-site="${id}">＋ 添加此站点监控</button></article>`).join('');
 $('#last-sync').textContent=demo?'演示模式 · 非实时数据':synced?`面板同步于 ${synced.toLocaleTimeString('zh-CN',{hour12:false})}`:'正在连接本地服务…';
}
function switchView(next){view=next;document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));for(const name of ['overview','sites','events'])$(`#${name}-view`).hidden=name!==view;const names={overview:'监控概览',sites:'站点管理',events:'活动日志'};$('#page-title').textContent=names[view];$('#breadcrumb').textContent=names[view];$('#page-subtitle').textContent={overview:'连接你的站点，让每一次在线变化都有迹可循。',sites:'统一管理站点连接，为更多能力预留空间。',events:'记录在线变化与连接状态，回看每一刻。'}[view];}
async function sync(){try{const response=await fetch('/api/state');if(!response.ok)throw Error();real=await response.json();synced=new Date();$('.running').innerHTML='<i class="dot"></i> 本地服务运行中';if(real.monitors.length&&demo){demo=false;sessionStorage.setItem('monitor-demo','off');}render();}catch{$('.running').textContent='本地服务连接中断';}}
function openDialog(site){$('#form-error').textContent='';if(site)$('#connect-form').elements.site.value=site;configureMode();$('#connect-dialog').showModal();}
$('#add-top').onclick=()=>openDialog();$('#add-empty').onclick=()=>openDialog();$('#close-dialog').onclick=$('#cancel-dialog').onclick=()=>$('#connect-dialog').close();
$('#connect-dialog').addEventListener('close',()=>{$('#connect-form').elements.password.value='';});
$('#exit-demo').onclick=()=>{demo=false;sessionStorage.setItem('monitor-demo','off');render();toast('已退出演示，当前显示真实监控数据');};
$('#refresh').onclick=async()=>{if(demo)return toast('演示模式不会请求真实站点，请先添加监控');try{await api('/api/refresh',{});toast('已请求立即检查，结果将在下一次面板同步时更新');await sync();}catch(e){toast(e.message);}};
$('#search').oninput=render;
$('.tabs').onclick=e=>{const b=e.target.closest('[data-filter]');if(!b)return;filter=b.dataset.filter;document.querySelectorAll('.tab').forEach(el=>el.classList.toggle('selected',el===b));render();};
$('nav').onclick=e=>{const b=e.target.closest('[data-view]');if(b)switchView(b.dataset.view);};
$('#manage-sites').onclick=()=>switchView('sites');$('#all-events').onclick=()=>switchView('events');
$('#site-cards').onclick=e=>{const b=e.target.closest('[data-site]');if(b)openDialog(b.dataset.site);};
$('#monitor-rows').onclick=async e=>{const b=e.target.closest('[data-action]');if(!b)return;const m=data().monitors.find(m=>m.id===b.dataset.id);if(b.dataset.action==='copy'){if(!m.ip)return toast('暂无可复制的 IP');try{await navigator.clipboard.writeText(m.ip);toast('IP 已复制');}catch{toast('浏览器不支持剪贴板，请手动复制');}return;}if(demo)return toast('这是演示记录。请退出演示后添加真实监控。');if(b.dataset.action==='delete'&&!confirm(`确认移除 ${m.target} 的监控？历史日志仍会保留。`))return;try{await api(`/api/${b.dataset.action}`,{id:m.id});await sync();toast('操作已完成');}catch(e){toast(e.message);}};
$('#connect-form').onsubmit=async e=>{e.preventDefault();const button=$('#connect-submit');button.disabled=true;button.textContent='正在安全连接…';$('#form-error').textContent='';try{await api('/api/connect',{...Object.fromEntries(new FormData(e.target)),mode:e.target.elements.site.value==='goj'?'personal':'json',allow_sudo:e.target.elements.site.value==='goj'&&e.target.elements.allow_sudo.checked});demo=false;sessionStorage.setItem('monitor-demo','off');$('#connect-dialog').close();e.target.reset();await sync();toast('连接成功，开始监控');}catch(err){$('#form-error').textContent=err.message;}finally{button.disabled=false;button.textContent='连接并开始监控 ↗';}};
$('#export-events').onclick=()=>{const blob=new Blob([JSON.stringify({demo,events:data().events},null,2)],{type:'application/json'});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`monitor-events-${demo?'demo':'local'}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
render();sync();setInterval(sync,5000);

function configureMode(){
 const f=$('#connect-form'), personal=f.elements.site.value==='goj';
 for(const key of ['target','login_path','status_path','user_field','password_field']){
  f.elements[key].required=!personal;
  f.elements[key].closest('label').hidden=personal;
 }
 f.querySelector('details').hidden=personal;
 $('#personal-info').hidden=!personal;
 $('#sudo-option').hidden=!personal;
 if(!personal)f.elements.allow_sudo.checked=false;
}
$('#connect-form').elements.site.onchange=configureMode;
