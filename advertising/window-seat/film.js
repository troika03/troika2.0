const {starts:s,lengths,duration}=window.cut;
const tl=gsap.timeline({paused:true});
window.__timelines={main:tl};
document.querySelector('#root').dataset.duration=duration;
const desks=document.querySelector('.desks');
for(const number of [1,2,3,4,5,6,7,8,9]){
  const desk=document.createElement('div');
  desk.className=number===4?'desk selected':'desk';
  desk.textContent=number===4?'Рома':String(number).padStart(2,'0');
  desks.append(desk);
}
function camera(when,seconds,sourceY,destY,scale,angle,yaw=0,x=0){
  const props={x,y:destY-69-341-(sourceY-341)*scale,scale,rotationZ:angle,rotationY:yaw,rotationX:-1.5};
  if(seconds===0)tl.set('#phone',props,when);
  else tl.to('#phone',{...props,duration:seconds,ease:'power2.inOut'},when);
}
function switchView(id,time){
  tl.set(['#home','#chat','#pdf','#reply'],{visibility:'hidden'},time);
  tl.set(id,{visibility:'visible'},time);
}
function highlight(id,time,end){
  tl.to(id,{boxShadow:'0 0 0 2px #b0dabe, 0 0 0 1200px rgba(0,5,2,.57)',position:'relative',zIndex:2,duration:.24},time);
  tl.to(id,{boxShadow:'0 0 0 0px transparent, 0 0 0 0px transparent',duration:.23},end-.23);
  tl.set(id,{zIndex:0},end);
}
camera(0,0,182,270,1.20,-5.8,-7,1);
camera(.2,2.5,182,280,1.25,-3.7,-4,-6);
tl.fromTo('.cold-msg',{rotation:-4.5,scale:1.02},{rotation:-2,scale:1.045,duration:1.62,ease:'sine.inOut'},0);
tl.fromTo('.cold-heart',{scale:.94},{scale:1.18,duration:.22,repeat:1,yoyo:true,ease:'power2.out'},.52);
tl.to('#hookTitle',{y:-18,opacity:0,duration:.23},s[1]-.55);
tl.to('#cold',{clipPath:'inset(0 0 100% 0 round 20px)',duration:.46,ease:'power3.inOut'},s[1]-.48);
tl.set(['#hookTitle','#cold'],{visibility:'hidden'},s[1]);
tl.fromTo('#transcript',{y:-7},{y:0,duration:.41,ease:'power3.out'},0);
camera(s[1],1.3,270,320,1.06,1.5,5);
switchView('#chat',s[2]-.30);
camera(s[2]-.30,.50,287,417,1.16,-3,-4,2);
highlight('#message',s[2]-.04,s[2]+1.69);
camera(s[2]+1.45,.65,375,440,1.19,-1.8,-1,8);
highlight('#windowMsg',s[2]+1.76,s[3]-.07);
camera(s[3]-.05,.58,476,465,1.18,3,6,1);
highlight('#attachment',s[3]+.18,s[5]-.1);
camera(s[4],.78,480,466,1.36,1.6,3,0);
switchView('#pdf',s[5]-.06);
camera(s[5]-.06,.42,298,387,1.09,-3.3,-6,0);
camera(s[5]+1.09,1.23,298,381,1.22,-1.9,-4,2);
tl.fromTo('.selected',{backgroundColor:'#e1e7dc'},{backgroundColor:'#a4ddaf',duration:.35},s[5]+2.77);
camera(s[5]+3.29,1.15,434,443,1.23,.8,1,0);
switchView('#chat',s[6]-.07);
camera(s[6]-.07,.54,400,435,1.24,-4,-5,9);
highlight('#windowMsg',s[6]+.12,s[7]+.59);
tl.fromTo('#heart',{scale:1},{scale:1.25,duration:.24,yoyo:true,repeat:1,ease:'power2.out'},s[7]+.39);
tl.to('#chatDim',{opacity:1,duration:.27},s[8]-.61);
tl.fromTo('#reactions',{autoAlpha:0,y:105},{autoAlpha:1,y:0,duration:.44,ease:'power3.out'},s[8]-.54);
camera(s[8]-.69,.65,600,487,1.22,2.8,4,0);
tl.set('.who',{autoAlpha:0},0);
tl.fromTo('.who',{autoAlpha:0,y:8},{autoAlpha:1,y:0,duration:.22},s[8]-.09);
camera(s[8]-.07,.83,620,460,1.54,.6,2,14);
tl.to('.who b',{color:'#78ebb1',duration:.2},s[8]);
switchView('#reply',s[9]-.02);
camera(s[9]-.02,.70,300,439,1.13,-2.1,-3,0);
tl.set(['.answer','#ruler'],{visibility:'hidden'},0);
tl.fromTo('.answer',{autoAlpha:0,y:7},{autoAlpha:1,y:0,duration:.30},s[10]-.06);
camera(s[10],.90,334,423,1.23,.8,2,2);
tl.fromTo('#ruler',{autoAlpha:0,x:80,rotation:-13},{autoAlpha:1,x:0,rotation:-8,duration:.50,ease:'power3.out'},s[10]+.83);
const captions=[
[[0,'Тройка, меня, кажется, позвали на свидание.'],[.72,'Что ответить?']],
[[0,'Покажи, что она написала.']],
[[0,'«Завтра в девять. Буду ждать.'],[.44,'Я оставила тебе место у окна».'],[.89,'Ну?']],
[[0,'А вложение ты открыл?']],
[[0,'Какое ещё вложение?']],
[[0,'План рассадки.'],[.30,'Контрольная по геометрии.'],[.65,'Кабинет двести четырнадцать.']],
[[0,'Подожди. А сердечко под сообщением?']],
[[0,'Нажми на него.'],[.44,'Посмотри, кто поставил.']],
[[0,'Вы.'],[.41,'А… Это я.']],
[[0,'Ладно. И что мне с собой брать?']],
[[0,'Линейку, Рома.'],[.43,'Цветы можешь оставить дома.']]
];
captions.forEach((row,i)=>row.forEach(([fraction,text],j)=>{
  const at=i===0&&j===0?0:s[i]+fraction*lengths[i];
  const end=j+1<row.length?s[i]+row[j+1][0]*lengths[i]:Math.min(s[i]+lengths[i]+.20,s[i+1]-.08);
  const cap=document.createElement('div');cap.className='cap';cap.textContent=text;document.querySelector('#caps').append(cap);
  tl.set(cap,{visibility:'visible'},at);tl.set(cap,{visibility:'hidden'},end);
}));
tl.fromTo('#brand',{autoAlpha:0},{autoAlpha:1,duration:.32},s[11]-.48);
tl.fromTo('#brand img:first-child',{scale:.88},{scale:1,duration:.62,ease:'power3.out'},s[11]-.42);
tl.set({},{},duration);
