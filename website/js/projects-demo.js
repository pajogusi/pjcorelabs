document.addEventListener('DOMContentLoaded', () => {
  const $ = id => document.getElementById(id);
  const tr = (key, fallback) => (typeof translations !== 'undefined' && translations[document.documentElement.lang || 'en'] && translations[document.documentElement.lang || 'en'][key]) || fallback;
  const kind=document.body.dataset.demoKind || 'barbers';
  const serviceOptions=kind==='nails'?[['manicure','svcManicure'],['pedicure','svcPedicure'],['gel','svcGel']]:[['haircut','demoHaircut'],['beard','demoBeard'],['both','demoBoth']];
  const serviceKey=Object.fromEntries(serviceOptions);
  const serviceSelect=$('demo-service');
  function translateServices(){const current=serviceSelect.value;serviceSelect.replaceChildren();for(const [value,key] of serviceOptions){const option=document.createElement('option');option.value=value;option.textContent=tr(key,value);serviceSelect.append(option);}if(serviceOptions.some(([v])=>v===current))serviceSelect.value=current;}
  translateServices();
  const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 1);
  const dateString = d => [d.getFullYear(), String(d.getMonth()+1).padStart(2,'0'), String(d.getDate()).padStart(2,'0')].join('-');
  $('demo-date').value = dateString(tomorrow);
  let bookings = [], editing = null, sequence = 1;
  function notify(key, fallback) { $('demo-notice').textContent = tr(key, fallback); }
  function reset() { editing = null; $('demo-form').reset(); $('demo-date').value = dateString(tomorrow); $('demo-submit').textContent = tr('demoCreate','Create appointment'); }
  function action(label, fn) { const b=document.createElement('button'); b.type='button'; b.textContent=label; b.addEventListener('click',fn); return b; }
  function render() {
    const list=$('demo-list'); list.replaceChildren();
    const sorted=[...bookings].sort((a,b)=>(a.date+a.time).localeCompare(b.date+b.time));
    if (!sorted.length) { const p=document.createElement('p');p.textContent=tr('demoEmpty','No appointments yet.');list.append(p); }
    sorted.forEach(item => {
      const card=document.createElement('div');card.className='demo-appointment';
      const heading=document.createElement('strong');heading.textContent=item.name;card.append(heading);
      const detail=document.createElement('p');detail.textContent=item.date+' · '+item.time+' · '+tr(serviceKey[item.service],item.service);card.append(detail);
      const controls=document.createElement('div');controls.className='demo-actions';
      controls.append(action(tr('demoEdit','Edit'),()=>{editing=item.id;$('demo-customer').value=item.name;$('demo-service').value=item.service;$('demo-date').value=item.date;$('demo-time').value=item.time;$('demo-submit').textContent=tr('demoSave','Save changes');$('demo-form').scrollIntoView({behavior:'smooth',block:'center'});}),
      action(tr('demoCancel','Cancel'),()=>{bookings=bookings.filter(b=>b.id!==item.id);if(editing===item.id)reset();notify('demoCancelled','Appointment cancelled.');render();}),
      action(tr('demoSms','Preview SMS'),()=>{const text=tr('demoSmsText','Demo only: appointment confirmed for');$('demo-notice').textContent=text+' '+item.name+' — '+item.date+' '+item.time+'. '+tr('demoNoSms','No SMS sent.');}));card.append(controls);list.append(card);
    });
    const history=$('demo-history');history.replaceChildren();
    const matches=sorted.filter(b=>b.name===$('demo-history-customer').value);
    const p=document.createElement('p');p.textContent=matches.length?matches.map(b=>b.date+' '+b.time+' · '+tr(serviceKey[b.service],b.service)).join(' | '):tr('demoNoHistory','No appointments for this customer.');history.append(p);
  }
  $('demo-form').addEventListener('submit', e => {
    e.preventDefault();
    const data={name:$('demo-customer').value,service:$('demo-service').value,date:$('demo-date').value,time:$('demo-time').value};
    if (!data.date || !data.time) return;
    const conflict=bookings.some(b=>b.id!==editing && b.date===data.date && b.time===data.time);
    if (conflict){notify('demoConflict','That time is already booked. Choose another time.');return;}
    if(editing){Object.assign(bookings.find(b=>b.id===editing),data);notify('demoUpdated','Appointment updated.');}
    else{bookings.push({...data,id:sequence++});notify('demoCreated','Appointment created.');}
    reset();render();
  });
  $('demo-clear').addEventListener('click',reset);
  $('demo-history-customer').addEventListener('change',render);
  document.querySelectorAll('[data-lang-button]').forEach(button=>button.addEventListener('click',()=>{translateServices();if(!editing)$('demo-submit').textContent=tr('demoCreate','Create appointment');else $('demo-submit').textContent=tr('demoSave','Save changes');$('demo-notice').textContent='';render();}));
  render();
});