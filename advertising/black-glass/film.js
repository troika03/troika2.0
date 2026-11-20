const scenes = [...document.querySelectorAll('section')];
const timeline = gsap.timeline({paused:true});
const cuts = window.cut.starts;
const end = window.cut.duration;
const each = (parent, selector) => [...parent.querySelectorAll(selector)];
const clamp = (value, lo=0, hi=1) => Math.min(hi,Math.max(lo,value));
const logo = new Path2D('M12 92V60C12 33.49 33.49 12 60 12H92A8 8 0 0 1 92 28H60C42.327 28 28 42.327 28 60V92A8 8 0 0 1 12 92Z M40 92V68C40 52.536 52.536 40 68 40H92A8 8 0 0 1 92 56H68C61.373 56 56 61.373 56 68V92A8 8 0 0 1 40 92Z M68 92V80C68 73.373 73.373 68 80 68H92A8 8 0 0 1 92 84H84V92A8 8 0 0 1 68 92Z');
const progress = scenes.map(() => {const i=document.createElement('i'),b=document.createElement('b');i.append(b);document.querySelector('#progress').append(i);return b});
function enter(items, from, at, duration=.6, stagger=0){
  const first=Array.isArray(items)?items[0]:items;
  const sceneIndex=scenes.indexOf(first.closest('section'));
  if(at>cuts[sceneIndex]) timeline.set(items,from,cuts[sceneIndex]);
  timeline.fromTo(items,{...from,immediateRender:false},{opacity:1,x:0,y:0,scale:1,rotationY:0,rotationX:0,rotationZ:0,ease:'power3.out',duration,stagger,immediateRender:false},at);
}
scenes.forEach((s,i)=>{
  const start=cuts[i];
  if(i) timeline.set(scenes[i-1],{visibility:'hidden'},start);
  timeline.set(s,{visibility:'visible'},start);
  if(i) enter(s.querySelector('h1'),{y:12,opacity:.15},start,.43);
  const object=s.querySelector('.stage').children[0];
  if(i===0) gsap.set(object,{scale:1});
  else if(i===2||i===3) enter(object,{scale:.87,rotationY:i===2?-22:18,rotationZ:i===2?-4:3,y:24},start,.95);
  else if(i!==4) enter(object,{scale:i===7?1.15:.94,y:17,opacity:.16},start,.7);
});
const S=i=>scenes[i],at=(i,t)=>cuts[i]+t;
enter(each(S(1),'.step'),{y:11,opacity:0},at(1,1.15),.5,.66);
enter(S(2).querySelector('.command'),{y:14,opacity:0},at(2,.35),.42);
timeline.fromTo('.fileScreen',{opacity:0,x:42},{opacity:1,x:0,duration:.48,ease:'power2.out',immediateRender:false},at(2,2.16));
timeline.set('.fileScreen',{opacity:0},cuts[2]);
timeline.set('.touch',{opacity:0},cuts[2]);
enter(S(2).querySelector('.fileShortcut'),{y:9,opacity:0},at(2,.90),.33);
timeline.fromTo(S(2).querySelector('.fileScreen img'),{scale:1},{scale:1.23,transformOrigin:'10% 28%',duration:2,ease:'sine.inOut',immediateRender:false},at(2,2.72));
timeline.to('.touch',{opacity:.9,duration:.2},at(2,1.76)).to('.touch',{scale:.55,duration:.17},at(2,1.99)).to('.touch',{opacity:0,scale:1.7,duration:.36},at(2,2.17));
enter(S(3).querySelector('.ask'),{y:12,opacity:0},at(3,1.96),.4);
enter(S(3).querySelector('.answer'),{y:12,opacity:0},at(3,3.05),.45);
enter(S(4).querySelector('.chip'),{scale:1.2,rotationY:-16},cuts[4],.9);
enter(S(4).querySelector('.document'),{y:15,opacity:0},at(4,1.45),.52);
enter(each(S(6),'.module'),{x:16,opacity:0},at(6,.67),.52,.67);
enter(each(S(6),'.module i'),{scale:.3,opacity:0},at(6,1.22),.32,.67);
enter(S(7).querySelector('.cta'),{y:11,opacity:0},at(7,1.65),.55);
timeline.to({t:0},{t:1,duration:end,ease:'none'},0);
function prepareCanvas(canvas, size) {
  const c=canvas.getContext('2d');
  c.setTransform(canvas.width/size,0,0,canvas.width/size,0,0);
  c.clearRect(0,0,size,canvas.height*size/canvas.width);return c;
}
function gradient(c, args, stops, type='linear'){
  const g=type==='radial'?c.createRadialGradient(...args):c.createLinearGradient(...args);
  stops.forEach(([n,color])=>g.addColorStop(n,color));return g;
}
function circle(c,x,y,r,style){
  c.beginPath();c.arc(x,y,r,0,Math.PI*2);c.fillStyle=style;c.fill();
}
function chrome(c,t, strength=1){
  const g=c.createConicGradient(-1.05+.2*Math.sin(t*.77),0,0);
  [[0,'#424247'],[.055,'#eeeeef'],[.10,'#8d8d92'],[.14,'#17171a'],[.29,'#4c4c52'],[.37,'#f1f1f1'],[.40,'#828289'],[.51,'#212123'],[.62,'#9999a0'],[.69,'#e4e4e6'],[.72,'#58585e'],[.81,'#171719'],[.9,'#797980'],[1,'#424247']].forEach(([p,col])=>g.addColorStop(p,col));return g;
}
function drawMedal(canvas,t){
  const c=prepareCanvas(canvas,460);c.save();c.translate(230,224);
  const rim=chrome(c,t);
  circle(c,0,8,181,'#09090a');circle(c,0,3.5,181,rim);circle(c,0,1,178,'#18181b');circle(c,0,0,175.8,rim);circle(c,0,0,174,'#0b0b0d');
  const face=gradient(c,[-70,-111,6,10,21,211],[[0,'#5b5b61'],[.21,'#38383e'],[.58,'#19191d'],[.84,'#101013'],[1,'#333337']],'radial');
  circle(c,0,0,169,face);
  for(let i=0;i<148;i++){
    const a=i*2*Math.PI/148;const b=i%5===0?155:161;
    c.beginPath();c.moveTo(b*Math.cos(a),b*Math.sin(a));c.lineTo(165.5*Math.cos(a),165.5*Math.sin(a));c.strokeStyle='rgba(230,230,238,'+(.16+.48*(.5+.5*Math.cos(a*2+t*.63)))+')';c.lineWidth=i%5===0?1.5:.85;c.stroke();
  }
  circle(c,0,0,150,rim);circle(c,0,0,148.9,'#141416');
  const lens=gradient(c,[-115,-123,117,114],[[0,'#727278'],[.16,'#48484e'],[.29,'#242429'],[.42,'#19191d'],[.53,'#141416'],[.8,'#08080b'],[1,'#37373d']]);circle(c,0,0,145.5,lens);
  c.save();c.beginPath();c.arc(0,0,145,0,Math.PI*2);c.clip();
  const shift=15*Math.sin(.82*t);c.translate(shift,0);
  c.beginPath();c.moveTo(-205,-25);c.bezierCurveTo(-80,2,97,-60,160,-149);c.lineTo(160,-190);c.lineTo(-200,-190);c.closePath();
  c.fillStyle=gradient(c,[-100,-130,4,8],[[0,'#ffffff03'],[.66,'#ffffff12'],[1,'#ffffff03']]);c.fill();c.restore();
  c.save();c.translate(-94,-98);c.scale(1.73,1.73);
  for(let z=6;z>=0;z--){c.save();c.translate(z*.3,z*.77);c.fillStyle=z?'#29292e':gradient(c,[18,14,90,98],[[0,'#fff'],[.32,'#d8d8de'],[.52,'#babac2'],[.70,'#f1f1f4'],[1,'#a4a4af']]);c.fill(logo);c.restore()}
  c.strokeStyle='#ffffffb0';c.lineWidth=.55;c.stroke(logo);c.restore();
  c.beginPath();c.arc(0,0,180,-2.37,-.98+.08*Math.sin(t));c.lineWidth=1.4;c.strokeStyle='#f5f5fa';c.stroke();c.restore();
}
function waveform(canvas,t,ribbon){
  const w=480,h=canvas.height*w/canvas.width, c=prepareCanvas(canvas,w),cy=h*.50;
  if(ribbon){
    for(let k=0;k<29;k++){
      const s=k/28;c.beginPath();
      for(let x=0;x<=w;x+=3){
        const u=x/w, amp=Math.sin(Math.PI*u)**1.2;
        const y=cy+amp*(33*Math.sin(6.2*u+t*3.8+s*4)+24*Math.sin(12*u-t*1.85+s*3.7))+amp*(s-.5)*31;
        if(!x)c.moveTo(x,y);else c.lineTo(x,y)
      }
      c.strokeStyle='rgba(234,234,245,'+(.15+.66*Math.sin(Math.PI*s)**2)+')';c.lineWidth=k%5===0?1.4:.78;c.stroke();
    }
  }else{
    for(let i=0;i<70;i++){
      const u=i/69, env=.13+.86*Math.sin(Math.PI*u)**1.5;
      const a=4+env*Math.abs(Math.sin(i*.63+t*6.8)*.55+Math.cos(i*.21-t*4.1)*.43)*h*.86;
      c.fillStyle='rgba(239,239,246,'+(.44+.5*env)+')';c.fillRect(i*w/70,cy-a/2,3.4,a)
    }
  }
}
function circuit(t){
  const canvas=document.querySelector('#circuit'),c=prepareCanvas(canvas,540);c.save();c.translate(270,240);
  for(let side=0;side<4;side++){c.save();c.rotate(side*Math.PI/2);
    for(let i=-5;i<=5;i++){const y=i*13,extend=17+(5-Math.abs(i))*4;
      const pts=[[82,y],[101+extend,y],[126+extend,y+i*5],[166+extend+(Math.abs(i)%3)*9,y+i*5]];
      c.beginPath();pts.forEach(([x,y],n)=>n?c.lineTo(x,y):c.moveTo(x,y));c.strokeStyle=i%2?'#4b4b53':'#626269';c.lineWidth=1;c.stroke();const [x,lastY]=pts[3];circle(c,x,lastY,2.4,'#9999a1');
      const phase=(t*.46+Math.abs(i)*.11+side*.18)%1,seg=Math.min(2,Math.floor(phase*3)),f=phase*3-seg;
      circle(c,pts[seg][0]*(1-f)+pts[seg+1][0]*f,pts[seg][1]*(1-f)+pts[seg+1][1]*f,1.6,'#d4d4d9');
    }c.restore();
  }c.restore();
}
function frame(t){
  timeline.seek(t,false);let idx=cuts.findLastIndex(n=>t>=n);idx=Math.max(0,idx);const d=t-cuts[idx];
  document.querySelector('#pageNo').textContent=String(idx+1).padStart(2,'0');
  progress.forEach((b,i)=>b.style.transform='scaleX('+clamp((t-cuts[i])/((cuts[i+1]??end)-cuts[i]))+')');
  const cue=window.cut.caps.findLast(([start])=>t>=start);
  document.querySelector('#cap').textContent=cue?cue[1]:'';
  document.querySelector('#root').classList.toggle('opening',idx===0);
  document.querySelector('#root').style.setProperty('--intro-caption',clamp(d/.24));
  if(idx===7)drawMedal(scenes[idx].querySelector('canvas'),d);
  if(idx===1||idx===3)waveform(scenes[idx].querySelector('.wave'),d,idx===3);
  if(idx===4)circuit(d);
  if(idx===5){const f=clamp((d-.35)/2.11);document.querySelector('#value').textContent=String(Math.round(824*(1-f)**3))}
}
window.__timelines={main:{seek:frame}};frame(0);
