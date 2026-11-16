import React, {CSSProperties} from 'react';
import {AbsoluteFill, Audio, Easing, Img, interpolate, staticFile, useCurrentFrame} from 'remotion';

export const FPS = 30;
export const LENGTH = 28.8;
const MINT = '#a9efc7';
const PAPER = '#f3f7f1';
const INK = '#0b0d10';
const CUT = {light: 4.26, flash: 6.43, search: 8.95, answer: 13, slides: 15.55, file: 18.65, brand: 22.45};
const ease = Easing.bezier(0.18, 0.81, 0.24, 1);
const tween = (time: number, from: number, to: number, smooth = ease) =>
  interpolate(time, [from, to], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: smooth});

const fill: CSSProperties = {position: 'absolute', inset: 0};
const at = (left: number, top: number, width?: number): CSSProperties =>
  ({position: 'absolute', left, top, width});

function Still({file, style}: {file: string; style?: CSSProperties}) {
  return <Img src={staticFile(file)} style={{display: 'block', width: '100%', ...style}}/>;
}

function Photo({name, scale = 1, x = 0, y = 0}: {
  name: string; scale?: number; x?: number; y?: number;
}) {
  return (
    <>
      <Still file={name + '.jpg'} style={{
        ...fill, width: 540, height: 960, objectFit: 'cover',
        transform: `translate(${x}px,${y}px) scale(${scale})`,
      }}/>
      <div style={{...fill, background: 'linear-gradient(180deg,#0709098a 0%,#07090917 39%,#0709095c 67%,#070909 100%)'}}/>
    </>
  );
}

function Background({warm = false}: {warm?: boolean}) {
  return <div style={{
    ...fill, background: warm
      ? 'radial-gradient(ellipse at 45% 48%,#443722,#161913 53%,#0b0d10 88%)'
      : 'radial-gradient(ellipse at 45% 49%,#184330,#101f19 47%,#0b0d10 86%)',
  }}/>;
}

function Caption({text, value = 1, top = 727}: {text: string; value?: number; top?: number}) {
  return <div style={{
    ...at(30, top, 440), color: PAPER, fontSize: 26, fontWeight: 720, letterSpacing: -0.8,
    lineHeight: 1.2, opacity: value, transform: `translateY(${(1 - value) * 15}px)`,
  }}>
    <span style={{
      background: '#101415ee', padding: '6px 11px', borderRadius: 8, boxDecorationBreak: 'clone',
      WebkitBoxDecorationBreak: 'clone', whiteSpace: 'pre-line',
    }}>{text}</span>
  </div>;
}

function Reply({time, start, text, top = 748}: {time: number; start: number; text: string; top?: number}) {
  const show = tween(time, start, start + 0.29);
  const phase = time - start;
  return <div style={{
    ...at(32, top, 446), display: 'flex', alignItems: 'center', gap: 12, padding: '12px 13px',
    background: '#0b1815ef', border: '1px solid #84d3ae58', borderRadius: 13, opacity: show,
    transform: `translateY(${12 * (1 - show)}px)`,
  }}>
    <div style={{flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 3, width: 39, height: 39,
      borderRadius: '50%', background: '#284539', boxShadow: `0 0 ${7 + 4 * Math.sin(phase * 8)}px #5cdf9655`}}>
      {[0, 1, 2, 3, 4].map(index => (
        <div key={index} style={{
          width: 3, borderRadius: 4, background: MINT,
          height: 4 + Math.sin(phase * 14 + index * 1.3) ** 2 * (15 - Math.abs(index - 2) * 4),
        }}/>
      ))}
    </div>
    <div>
      <div style={{fontSize: 13, color: MINT, fontWeight: 700, marginBottom: 3}}>Тройка</div>
      <div style={{fontSize: 21, fontWeight: 680, letterSpacing: -0.45}}>{text}</div>
    </div>
  </div>;
}

function Logo({style}: {style?: CSSProperties}) {
  return <Still file="logo-ru-reverse.svg" style={style}/>;
}

function Headline({children, size = 60, top = 130, progress = 1}: {
  children: React.ReactNode; size?: number; top?: number; progress?: number;
}) {
  return <div style={{
    ...at(32, top, 470), color: PAPER, fontSize: size, fontWeight: 780, lineHeight: 0.99,
    letterSpacing: -0.066 * size, opacity: progress, transform: `translateY(${17 * (1 - progress)}px)`,
    textShadow: '0 10px 29px #07130db3',
  }}>{children}</div>;
}

function Phone({x, y, width, tilt, pulse = 0}: {
  x: number; y: number; width: number; tilt: number; pulse?: number;
}) {
  const shell = width * 0.035;
  const micX = shell + (width - 2 * shell) * 256 / 390;
  const micY = shell + (width - 2 * shell) * 281 / 390;
  return (
    <div style={{
      ...at(x, y, width), padding: shell, borderRadius: width * 0.123,
      background: 'linear-gradient(139deg,#87968a,#202223 35%,#111317 68%,#626f63)',
      boxShadow: '0 32px 66px #000a,0 0 0 1px #b7edca44', transform: `rotate(${tilt}deg)`,
    }}>
      <Still file="android-home.png" style={{borderRadius: width * 0.096}}/>
      {pulse > 0 && <div style={{
        ...at(micX - (17 + 10 * pulse), micY - (17 + 10 * pulse), 34 + 20 * pulse),
        height: 34 + 20 * pulse, opacity: 0.54 * pulse, borderRadius: '50%',
        border: '2px solid #85ffc2', boxShadow: '0 0 15px #85ffc2aa',
      }}/>}
    </div>
  );
}

function Hook({time}: {time: number}) {
  const title = tween(time, 0.02, 0.36);
  const update = tween(time, 1.52, 1.72);
  const cutaway = time >= 2.62;
  return (
    <>
      {cutaway
        ? <>
          <Photo name="floor" scale={1.23 + (time - 2.62) * 0.026} x={-11} y={-20}/>
          <div style={{...fill, background: '#080c0d', opacity: 0.88}}/>
        </>
        : <Photo name="portrait" scale={1.01 + time * 0.015 + update * 0.12} x={-2 - update * 6} y={update * 5}/>}
      <div style={{
        ...at(32, 130), padding: '8px 12px', borderRadius: 9, background: '#0d1515dd', color: MINT,
        fontSize: 20, fontWeight: 680, display: 'flex', alignItems: 'center', gap: 8,
      }}><span style={{width: 7, height: 7, borderRadius: 8, background: '#ffbd84'}}/>Созвон через 5 минут</div>
      <Headline top={613} size={60} progress={title}>
        Флешка упала<br/><span style={{color: MINT}}>под стол.</span>
      </Headline>
    </>
  );
}

function Light({time}: {time: number}) {
  const local = time - CUT.light;
  const entry = tween(time, CUT.light, CUT.light + 0.55);
  const tape = tween(time, 4.38, 4.59);
  const pulse = (0.45 + Math.sin(local * 15) ** 2 * 0.55) * tween(time, 4.45, 4.77);
  if (time < CUT.flash) {
    return <>
      <Background/>
      <Logo style={{...at(35, 137, 170), opacity: entry}}/>
      <Phone x={154 + 38 * (1 - entry)} y={260 + 98 * (1 - entry)} width={214} tilt={-10 + 5 * entry} pulse={pulse}/>
      <Caption text="«Тройка, включи фонарик»" value={tape}/>
    </>;
  }
  const beam = tween(time, CUT.flash, 6.74);
  const cue = tween(time, 6.68, 7.07);
  return (
    <>
      <Photo name="floor" scale={1.1 + 0.13 * beam + 0.034 * (time - CUT.flash)} x={-12 * beam} y={-21 * beam}/>
      <div style={{...fill, background: INK, opacity: (1 - beam) * 0.88}}/>
      <div style={{
        ...at(208, 490, 90), height: 57, opacity: cue * 0.8, transform: 'rotate(-9deg)',
        border: '1.5px solid #d0ffe6', borderRadius: 20, boxShadow: '0 0 18px #90ffbb4f',
      }}/>
      <Headline top={674} size={49} progress={cue}>Нашёл.</Headline>
      <Reply time={time} start={6.77} text="Фонарик включён."/>
    </>
  );
}

function Desk({time, start, offset = 0, dim = 0}: {time: number; start: number; offset?: number; dim?: number}) {
  const travel = tween(time, start, start + 1.54);
  return (
    <>
      <div style={{...fill, transform: `translate(${-18 * travel}px,${23 * travel + offset}px) scale(${1.04 + 0.15 * travel})`}}>
        <Still file="desk.jpg" style={{...at(0, -60, 540), height: 1080}}/>
        <div style={{...at(130, 281, 257), height: 163, overflow: 'hidden', borderRadius: 5, opacity: 0.94,
          background: '#141b1b'}}>
          <Still file="windows-home.png" style={{height: '100%', objectFit: 'cover'}}/>
        </div>
      </div>
      <div style={{...fill, background: 'linear-gradient(180deg,#070b0b6b,transparent 36%,#070b0b 100%)'}}/>
      <div style={{...fill, opacity: dim, background: INK}}/>
    </>
  );
}

function Keycap({text}: {text: string}) {
  return <span style={{
    padding: '7px 12px', border: '1px solid #acb6aa', boxShadow: '0 3px 0 #aaafa6',
    color: '#172b24', fontWeight: 745, background: '#fff', borderRadius: 8,
  }}>{text}</span>;
}

function Search({time}: {time: number}) {
  const build = tween(time, CUT.answer, CUT.answer + 0.65);
  const textIn = tween(time, 9.11, 9.51);
  const done = tween(time, CUT.answer, CUT.answer + 0.28);
  return (
    <>
      <Desk time={time} start={CUT.search} offset={-24 * build} dim={0.34 * build}/>
      <Headline top={130} size={49} progress={tween(time, CUT.search, CUT.search + 0.55)}>
        {time < CUT.answer ? <>Дальше —<br/>вопрос.</> : <>Есть<br/><span style={{color: MINT}}>источник.</span></>}
      </Headline>
      {time < CUT.answer && <Caption text={'«Как записать экран в Windows?\nНайди официальный источник»'} value={textIn}/>}
      <div style={{
        ...at(32, 479, 454), borderRadius: 26, padding: '23px 25px 28px', color: '#0d2520',
        background: 'linear-gradient(154deg,#f7faf3,#e2eee1)', boxShadow: '0 28px 70px #000b',
        opacity: done, transform: `translateY(${34 * (1 - build)}px) scale(${0.95 + 0.05 * build})`,
      }}>
        <div style={{fontSize: 17, fontWeight: 680, color: '#476456'}}>Поддержка Microsoft</div>
        <div style={{fontSize: 27, fontWeight: 760, letterSpacing: -1.10, marginTop: 9}}>Запись экрана в Windows 11</div>
        <div style={{display: 'flex', alignItems: 'center', gap: 8, fontSize: 22, marginTop: 19}}>
          <Keycap text="Win"/><span>+</span><Keycap text="Shift"/><span>+</span><Keycap text="R"/>
        </div>
        <div style={{fontSize: 16, marginTop: 21, color: '#476456'}}>Выбери область и начни запись</div>
      </div>
      {time >= CUT.answer && <Reply time={time} start={13.12} text="Нашла. Win + Shift + R."/>}
    </>
  );
}

const slideText = [
  ['Запись экрана', 'Короткая инструкция для Windows 11'],
  ['Открой запись', 'Закрой лишние окна и нажми Win + Shift + R'],
  ['Выбери область', 'Нажми «Начать», затем останови и сохрани видео'],
];

function SlideCard({index, x, y, height, tilt = 0, opacity = 1, compact = false}: {
  index: number; x: number; y: number; height: number; tilt?: number; opacity?: number; compact?: boolean;
}) {
  return <div style={{
    ...at(x, y, compact ? 417 : 410), height, borderRadius: 15, overflow: 'hidden', opacity,
    background: index === 0 ? '#d8f2df' : '#f4f6ee', color: '#10271d',
    padding: '17px 19px', transform: `rotate(${tilt}deg)`, boxShadow: '0 16px 35px #0006',
  }}>
    <div style={{fontSize: 13, letterSpacing: 1.2, color: '#3f6754', fontWeight: 740}}>0{index + 1} / 03</div>
    <div style={{fontSize: compact ? 25 : 39, fontWeight: 795, letterSpacing: -1.3, marginTop: compact ? 4 : 30}}>
      {slideText[index][0]}
    </div>
    <div style={{fontSize: compact ? 15 : 20, marginTop: 4, color: '#335849', lineHeight: 1.18}}>{slideText[index][1]}</div>
    {!compact && <div style={{position:'absolute', right: -42, bottom: -40, width: 166, height: 166,
      borderRadius: 166, border: '25px solid #91cfae', opacity: 0.7}}/>}
  </div>;
}

function Slides({time}: {time: number}) {
  const pull = tween(time, CUT.file, CUT.file + 1.22);
  const file = tween(time, 19.83, 20.31);
  const caption = tween(time, 15.77, 16.12) * (1 - tween(time, CUT.file + 0.3, CUT.file + 0.66));
  const preview = tween(time, 16.98, 17.95);
  const stack = preview * (1 - tween(time, CUT.file, CUT.file + 0.56));
  return (
    <>
      <Background/>
      <Headline top={131} size={50} progress={tween(time, CUT.slides, CUT.slides + 0.45)}>
        {time < CUT.file ? <>Превращаем<br/>ответ в слайды.</> : <>Три слайда.<br/><span style={{color:MINT}}>Один файл.</span></>}
      </Headline>
      {stack > 0 && <>
        <SlideCard index={2} x={69 + preview * 16} y={370 - preview * 5} height={199} tilt={8 * preview} opacity={stack * 0.64}/>
        <SlideCard index={1} x={62 + preview * 6} y={379 - preview * 5} height={207} tilt={3.4 * preview} opacity={stack * 0.8}/>
        <SlideCard index={0} x={51 - 5 * preview} y={389 - preview * 26} height={221} tilt={-6.5 * preview} opacity={stack}/>
      </>}
      {pull > 0 && [0, 1, 2].map((index) => (
        <SlideCard key={index} index={index} x={40 + index * 8}
          y={316 + index * 119 + (1 - pull) * (70 - index * 45)}
          height={104} compact opacity={pull} tilt={(index - 1) * (1 - pull) * 7}/>
      ))}
      {file > 0 && <div style={{
        ...at(49, 682, 434), padding: '15px 17px', borderRadius: 14, display: 'flex', alignItems: 'center', gap: 12,
        background: '#21372e', border: '1px solid #4c6c5d', color: PAPER, opacity: file, fontSize: 21, fontWeight: 680,
        transform: `translateY(${12 * (1 - file)}px)`,
      }}>
        <span style={{padding:'5px 7px',fontSize:12,borderRadius:5,background:MINT,color:'#183128'}}>PPTX</span>
        Запись экрана.pptx
      </div>}
      <Caption text={'«А теперь собери по этой\nинструкции три слайда»'} value={caption}/>
      {time >= 20.02 && <Reply time={time} start={20.02} text="Слайды готовы. Выступать тебе." top={748}/>}
    </>
  );
}

function Brand({time}: {time: number}) {
  const pop = tween(time, CUT.brand, 23.17);
  const ask = tween(time, 26.12, 26.63);
  return (
    <>
      <Background/>
      <div style={{...at(32, 149, 474), opacity: pop, transform: `translateY(${24 * (1 - pop)}px)`}}>
        <Logo style={{width: 321, margin: '0 auto'}}/>
        <div style={{fontSize: 29, fontWeight: 700, letterSpacing: -0.96, marginTop: 17, textAlign: 'center'}}>Голосовая помощница</div>
        <div style={{fontSize: 18, color: MINT, marginTop: 8, fontWeight: 550, textAlign: 'center'}}>Android · Windows</div>
      </div>
      <div style={{...fill, opacity: pop}}>
        <div style={{
          ...at(151, 441 + 76 * (1 - pop), 351), padding: 7, borderRadius: 13, background: '#3e5047',
          boxShadow: '0 28px 48px #0009', transform: 'rotate(4deg)',
        }}><Still file="windows-home.png" style={{borderRadius: 7}}/></div>
        <Phone x={43} y={391 + 78 * (1 - pop)} width={141} tilt={-9}/>
      </div>
      <div style={{
        ...at(42, 754, 456), textAlign: 'center', fontSize: 28, color: MINT, fontWeight: 720,
        opacity: ask, transform: `translateY(${16 * (1 - ask)}px)`, letterSpacing: -0.8,
      }}>Что поручишь Тройке?</div>
    </>
  );
}

export function TroikaFilm({sound = true}: {sound?: boolean}) {
  const time = useCurrentFrame() / FPS;
  return (
    <AbsoluteFill style={{background: INK, color: PAPER, fontFamily: 'Golos, Arial, sans-serif', overflow: 'hidden'}}>
      <div style={{position: 'absolute', width: 540, height: 960, transform: 'scale(2)', transformOrigin: 'top left', overflow: 'hidden'}}>
        {time < CUT.light && <Hook time={time}/>}
        {time >= CUT.light && time < CUT.search && <Light time={time}/>}
        {time >= CUT.search && time < CUT.slides && <Search time={time}/>}
        {time >= CUT.slides && time < CUT.brand && <Slides time={time}/>}
        {time >= CUT.brand && <Brand time={time}/>}
      </div>
      {sound && <Audio src={staticFile('soundtrack.wav')}/>}
    </AbsoluteFill>
  );
}
