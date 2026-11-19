const {lines, duration, reminder} = window.film;
document.querySelector('.sheet').innerHTML = reminder;
const firstReminder = document.querySelector('.sheet g[data-name="task-detail"]');
firstReminder.style.opacity='1';
const reminderTime=firstReminder.querySelector('[data-name="end"] text');
reminderTime.setAttribute('font-size','17');
reminderTime.setAttribute('x','-14');
reminderTime.setAttribute('fill','#72edb3');
const focusRect=document.createElementNS('http://www.w3.org/2000/svg','rect');
Object.entries({x:-4,y:1,width:354,height:75,rx:9,fill:'#52dc991a',stroke:'#58cf91','stroke-width':1.5}).forEach(([name,value])=>focusRect.setAttribute(name,value));
firstReminder.prepend(focusRect);
const timeline = gsap.timeline({paused:true,defaults:{ease:'power2.inOut'}});
window.__timelines = {main:timeline};
const start = index => lines[index][0];
const voiceStart = start(2), proof = start(8), more = start(9), documentStart = start(11), end = start(14);
function reveal(id, previous, time) {
  timeline.set(id,{visibility:'visible'},time);
  timeline.fromTo(id,{clipPath:'inset(100% 0 0 0 round 22px)'},{clipPath:'inset(0% 0 0 0 round 0px)',duration:.42},time);
  timeline.set(previous,{visibility:'hidden'},time+.43);
}
timeline.fromTo('#macro',{scale:1.13,rotation:-10},{scale:.86,rotation:-2,duration:voiceStart,ease:'sine.inOut'},0);
timeline.fromTo('#intro h1 strong',{y:9},{y:0,duration:.45,ease:'power3.out'},0);
reveal('#voice','#intro',voiceStart);
timeline.fromTo('.hero',{rotation:-6,scale:.94,y:26},{rotation:0,scale:1.02,y:0,duration:Math.max(1,start(5)-voiceStart),ease:'power3.out'},voiceStart);
timeline.to('.hero',{scale:1.10,y:-10,duration:proof-start(5),ease:'sine.inOut'},start(5));
const wave = document.querySelector('.wave');
for(let i=0;i<15;i++){
  const bar=document.createElement('i');wave.append(bar);
  timeline.fromTo(bar,{scaleY:.16},{scaleY:.40+.60*Math.abs(Math.sin(i*2.71)),duration:.17+(i%4)*.04,repeat:12,yoyo:true,ease:'sine.inOut'},start(6)+i*.013);
}
timeline.set('.wave',{opacity:0},0).to('.wave',{opacity:1,duration:.18},start(6));
reveal('#evidence','#voice',proof);
timeline.fromTo('#rem',{scale:.91,y:21},{scale:1,y:0,duration:.62,ease:'power3.out'},proof);
timeline.fromTo('.sheet',{y:-25},{y:-123,duration:.78,ease:'power3.out'},proof+.13);
timeline.fromTo(focusRect,{opacity:0},{opacity:1,duration:.3},proof+.55);
reveal('#more','#evidence',more);
timeline.fromTo('.source',{scale:.97,y:11},{scale:1.025,y:0,duration:documentStart-more,ease:'sine.inOut'},more);
timeline.set(['.doc','#docTitle'],{visibility:'hidden'},0);
timeline.set(['.doc','#docTitle'],{visibility:'visible'},documentStart);
timeline.set('#featureTitle',{visibility:'hidden'},documentStart);
timeline.fromTo('.doc',{clipPath:'inset(100% 0 0 0)',y:12},{clipPath:'inset(0% 0 0 0)',y:0,duration:.44},documentStart);
timeline.to('.doc',{scale:1.035,duration:end-documentStart-.5,ease:'sine.inOut'},documentStart+.45);
timeline.set('#end',{visibility:'visible'},end);
timeline.fromTo('#end',{clipPath:'circle(0% at 50% 43%)'},{clipPath:'circle(85% at 50% 43%)',duration:.63},end);
timeline.fromTo('#endMark',{scale:.71,rotation:-7},{scale:1,rotation:0,duration:.85,ease:'power3.out'},end+.12);
timeline.fromTo('#end h2',{y:18,opacity:0},{y:0,opacity:1,duration:.48},end+.33);
timeline.fromTo('#endline',{opacity:0,y:7},{opacity:1,y:0,duration:.3},start(17));
for(let i=1;i<17;i++){
  const cap=document.createElement('div');cap.className='cap';cap.textContent=lines[i][1];document.querySelector('#caption').append(cap);
  timeline.set(cap,{visibility:'visible'},start(i));
  timeline.fromTo(cap,{opacity:0,y:5},{opacity:1,y:0,duration:.11,ease:'power2.out'},start(i));
  timeline.set(cap,{visibility:'hidden'},start(i+1));
}
timeline.set({}, {}, duration);document.querySelector('#root').dataset.duration=duration;
