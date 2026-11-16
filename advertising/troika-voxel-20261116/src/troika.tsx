import React, {useLayoutEffect, useRef} from 'react';
import {AbsoluteFill, Img, staticFile, useCurrentFrame} from 'remotion';
import {Beat, beatAt, defaultEpisode, type Episode, FPS} from './beats';
import {buildStage, type Stage} from './stage';

const WHITE = '#f4f7ff';
const MINT = '#cbffe2';
const fade = (p: number) => 1 - (1 - Math.max(0, Math.min(1, p))) ** 3;

function StageCanvas({time, beat, end}: {time: number; beat: Beat; end: number}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const stage = useRef<Stage | null>(null);
  const last = useRef({time, beat, end});
  last.current = {time, beat, end};

  useLayoutEffect(() => {
    const element = canvas.current!;
    let cancelled = false;
    buildStage(element, {
      mark: staticFile('app-icon.png'),
      android: staticFile('android-home.png'),
      windows: staticFile('windows-home.png'),
    }).then((created) => {
      if (cancelled) {
        created.dispose();
        return;
      }
      stage.current = created;
      const initial = last.current;
      created.draw(initial.time, initial.beat, initial.end);
      element.dataset.ready = 'yes';
    }).catch((error: unknown) => {
      element.dataset.error = String(error);
      console.error(error);
    });
    return () => {
      cancelled = true;
      stage.current?.dispose();
      stage.current = null;
    };
  }, []);

  useLayoutEffect(() => { stage.current?.draw(time, beat, end); }, [time, beat, end]);

  return <canvas ref={canvas} aria-hidden style={{position: 'absolute', inset: 0, width: '100%', height: '100%'}}/>;
}

function Subtitle({time, beat}: {time: number; beat: Beat}) {
  const local = time - beat.start;
  if (!beat.lines) return null;
  const pause = beat.reaction === 'punch' ? 0.47 : beat.reaction === 'deadpan' ? 0.35 : 0;
  const lines = local < pause ? ['…'] : beat.lines;
  const hook = beat.reaction === 'late';
  const reveal = beat.start === 0 ? 1 : 0.7 + 0.3 * fade(local / 0.083);
  return (
    <div style={{
      position: 'absolute', top: 251, left: 60, right: 60, padding: '13px 12px',
      color: beat.speaker === 'troika' ? MINT : WHITE,
      fontSize: 48, lineHeight: 1.15, fontWeight: 720, textAlign: 'center',
      opacity: reveal, textShadow: '0 3px 4px #04040d, 0 3px 19px #000',
      whiteSpace: 'pre-line', letterSpacing: -1.2,
    }}>
      {hook ? <>
        <div>{lines[0]}</div>
        <div style={{
          color: '#ffc497', fontSize: 61, marginTop: 2,
          opacity: fade((local - 0.13) / 0.30),
        }}>{lines[1]}</div>
      </> : lines.join('\n')}
    </div>
  );
}

const insertCopy = {
  source: {label: 'Поддержка Microsoft', title: 'Запись экрана в Windows 11'},
  slides: {label: 'PPTX', title: 'Запись экрана.pptx', detail: 'Три слайда'},
  research: {label: 'Cornell University', title: 'Разбей задачу на небольшие шаги'},
  deck: {label: 'PPTX', title: 'Как перестать откладывать.pptx', detail: 'Три слайда'},
};

function ResultInsert({time, beat}: {time: number; beat: Beat}) {
  if (!beat.insert || beat.insert === 'light') return null;
  const copy = insertCopy[beat.insert];
  const read = fade((time - beat.start - 0.26) / 0.72);
  const slide = 'detail' in copy;
  return (
    <div style={{
      position: 'absolute', left: 135, bottom: 322, width: 760, padding: '23px 30px 24px',
      border: '1px solid #a0d7c658', borderRadius: 29, color: WHITE,
      background: 'linear-gradient(150deg,#17262bf5,#101924fc)', boxShadow: '0 17px 50px #0009',
      opacity: read, transform: `translateY(${34 * (1 - read)}px)`,
    }}>
      {slide ? <div style={{display: 'flex', alignItems: 'center', gap: 19}}>
        <div style={{
          color: '#123025', background: '#97ebba', borderRadius: 10, padding: '11px 15px',
          fontSize: 22, fontWeight: 800, letterSpacing: 1,
        }}>{copy.label}</div>
        <div>
          <div style={{fontSize: 34, fontWeight: 735}}>{copy.title}</div>
          <div style={{fontSize: 23, color: '#bad3c7', marginTop: 1}}>{copy.detail}</div>
        </div>
      </div> : <>
        <div style={{fontSize: 25, fontWeight: 690, color: MINT}}>{copy.label}</div>
        <div style={{fontSize: 34, fontWeight: 735, marginTop: 3}}>{copy.title}</div>
      </>}
    </div>
  );
}

function End({time, start}: {time: number; start: number}) {
  const arrive = fade((time - start - 0.18) / 0.74);
  return (
    <div style={{
      position: 'absolute', top: 230, left: 100, right: 100, textAlign: 'center',
      color: WHITE, textShadow: '0 3px 14px #040516', opacity: arrive,
      transform: `translateY(${24 * (1 - arrive)}px)`,
    }}>
      <div style={{display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 25}}>
        <Img src={staticFile('app-icon.png')} style={{width: 111, height: 111}}/>
        <Img src={staticFile('wordmark-white.svg')} style={{width: 291, display: 'block'}}/>
      </div>
      <div style={{fontSize: 39, fontWeight: 720, letterSpacing: -1.1, marginTop: 21}}>Голосовая помощница</div>
      <div style={{fontSize: 27, fontWeight: 560, letterSpacing: 0.3, marginTop: 10, color: MINT}}>Android · Windows</div>
    </div>
  );
}

export function TroikaFilm({episode = defaultEpisode}: {episode?: Episode}) {
  const time = useCurrentFrame() / FPS;
  const {beat, end} = beatAt(time, episode);
  return (
    <AbsoluteFill style={{background: '#101528', fontFamily: 'Golos, Arial, sans-serif', overflow: 'hidden'}}>
      <StageCanvas time={time} beat={beat} end={end}/>
      <AbsoluteFill style={{
        pointerEvents: 'none',
        background: 'radial-gradient(ellipse at 49% 55%,transparent 42%,#080a2145 100%),linear-gradient(180deg,#03051370 0%,transparent 38%,transparent 79%,#06081764 100%)',
      }}/>
      <Subtitle time={time} beat={beat}/>
      <ResultInsert time={time} beat={beat}/>
      {beat.view === 'wide' && <End time={time} start={beat.start}/>}
    </AbsoluteFill>
  );
}
