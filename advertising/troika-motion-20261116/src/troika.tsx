import React, {CSSProperties} from 'react';
import {
  AbsoluteFill, Audio, Easing, Img, interpolate, random, staticFile, useCurrentFrame,
} from 'remotion';

export const FPS = 30;
export const LENGTH = 18;
const MINT = '#a7efc7';
const AMBER = '#ffb665';
const INK = '#0b0c10';
const GLOW = '#3ddc97';
const WHITE = '#f4f7f4';
const CUT = {listen: 3.2, result: 8.8, brand: 14.1};
const FONT = 'Golos, Arial, sans-serif';
const OPTIONS = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const points = Array.from({length: 44}, (_, index) => ({
  x: random(`x-${index}`) * 1080,
  y: random(`y-${index}`) * 1920,
  r: 0.7 + 2.1 * random(`size-${index}`),
  alpha: 0.12 + 0.46 * random(`opacity-${index}`),
  drift: 12 + 35 * random(`drift-${index}`),
}));

const tween = (time: number, start: number, end: number, from = 0, to = 1) =>
  interpolate(time, [start, end], [from, to], {...OPTIONS, easing: Easing.bezier(0.22, 1, 0.36, 1)});

const center: CSSProperties = {position: 'absolute', left: '50%', translate: '-50% 0'};
const row: CSSProperties = {display: 'flex', alignItems: 'center'};

function Backdrop({time, heat}: {time: number; heat: boolean}) {
  const color = heat ? AMBER : MINT;
  return (
    <AbsoluteFill style={{
      background: heat
        ? 'radial-gradient(ellipse at 50% 58%, #352013 0%, #211510 42%, #100e0b 83%)'
        : 'radial-gradient(ellipse at 52% 49%, #173b2e 0%, #11221e 47%, #0b0c10 87%)',
    }}>
      <AbsoluteFill style={{
        backgroundImage: 'linear-gradient(#ffffff08 1px, transparent 1px), linear-gradient(90deg,#ffffff08 1px,transparent 1px)',
        backgroundSize: '72px 72px',
        maskImage: 'radial-gradient(ellipse at center, black, transparent 77%)',
      }}/>
      <svg width="1080" height="1920" style={{position: 'absolute'}}>
        {points.map((point) => (
          <circle key={point.x} cx={point.x + 8 * Math.sin(time + point.x)}
            cy={(point.y + 1920 - time * point.drift % 1920) % 1920} r={point.r}
            opacity={point.alpha * (0.58 + 0.27 * Math.sin(point.y + time * 1.8))}
            fill={color}/>
        ))}
      </svg>
      <AbsoluteFill style={{
        backgroundImage: `url(${staticFile('grain.png')})`, opacity: 0.16,
        mixBlendMode: 'soft-light',
      }}/>
    </AbsoluteFill>
  );
}

function Lines({time, heat, listening = 0}: {time: number; heat: boolean; listening?: number}) {
  const tint = heat ? AMBER : MINT;
  const view = 800;
  const middle = view / 2;
  const paths = Array.from({length: 5}, (_, layer) => {
    const rotation = time * (heat ? 0.8 : 0.48) + layer * 0.68;
    const baseRadius = 274 - layer * 8;
    const amplitude = (heat ? 10 : 11 + 25 * listening) * (1 - layer * 0.1);
    const vertices = Array.from({length: 121}, (_, i) => {
      const angle = i / 120 * Math.PI * 2;
      const radius = baseRadius
        + amplitude * (Math.sin(5 * angle + rotation) * 0.7 + Math.sin(9 * angle - rotation * 1.3) * 0.3)
        + 7 * Math.sin(angle * 2 - time * 0.48 + layer * 0.5);
      return `${(middle + Math.cos(angle) * radius).toFixed(2)} ${(middle + Math.sin(angle) * radius).toFixed(2)}`;
    });
    return `M ${vertices.join(' L ')} Z`;
  });

  return (
    <svg width={view} height={view} viewBox={`0 0 ${view} ${view}`} style={{overflow: 'visible'}}>
      <defs>
        <linearGradient id={heat ? 'heat-edge' : 'voice-edge'} x1="0" x2="1" y1="0" y2="1">
          <stop stopColor={heat ? '#fff1ce' : '#e9fff2'}/>
          <stop offset=".42" stopColor={tint}/>
          <stop offset="1" stopColor={heat ? '#f46e37' : '#419875'}/>
        </linearGradient>
      </defs>
      <circle cx={middle} cy={middle} r={315} fill="none" stroke={tint} strokeWidth={1} opacity={0.16}/>
      <circle cx={middle} cy={middle} r={330} fill="none" stroke={tint} strokeWidth={4}
        strokeDasharray="1 15" opacity={0.27} transform={`rotate(${time * 7} 400 400)`}/>
      <path d={paths[0]} fill="none" stroke={tint} opacity={0.48} strokeWidth={14} style={{filter: 'blur(13px)'}}/>
      {paths.map((path, i) => (
        <path key={i} d={path} fill="none" stroke={`url(#${heat ? 'heat-edge' : 'voice-edge'})`}
          strokeWidth={i === 0 ? 3.2 : 1.25} opacity={0.9 - i * 0.16}/>
      ))}
    </svg>
  );
}

function Ring({time, top, scale, heat = false, listening = 0}: {
  time: number; top: number; scale: number; heat?: boolean; listening?: number;
}) {
  return (
    <div style={{
      ...center, display: 'grid', placeItems: 'center', top, width: 800, height: 800,
      transform: `scale(${scale})`,
    }}>
      <div style={{
        position: 'absolute', width: 640, height: 640, borderRadius: '50%',
        background: heat
          ? 'radial-gradient(circle,#ff88050d 18%, #c6571b1e 49%, #f882301b 58%, transparent 72%)'
          : 'radial-gradient(circle,#66e8ac03 30%, #41be8220 49%, #66e8ac13 57%, transparent 71%)',
      }}/>
      <Lines time={time} heat={heat} listening={listening}/>
    </div>
  );
}

function Reveal({time, start, children, style}: {
  time: number; start: number; children: React.ReactNode; style?: CSSProperties;
}) {
  const rise = tween(time, start, start + 0.58);
  return (
    <div style={{overflow: 'hidden', paddingBottom: 10, marginBottom: -10, ...style}}>
      <div style={{opacity: rise, transform: `translateY(${(1 - rise) * 54}px)`}}>{children}</div>
    </div>
  );
}

function Hook({time}: {time: number}) {
  const handoff = tween(time, 2.9, CUT.listen);
  const exit = tween(time, 2.87, 3.14);
  return (
    <AbsoluteFill>
      <Backdrop time={time} heat/>
      <div style={{
        position: 'absolute', left: 91, top: 382, width: 880, opacity: 1 - exit,
        transform: `translateY(${-46 * exit}px)`,
      }}>
        <Reveal time={time} start={0.04} style={{fontSize: 83, fontWeight: 720, letterSpacing: -5}}>
          Только не забудь
        </Reveal>
        <Reveal time={time} start={0.24} style={{fontSize: 66, letterSpacing: -3.4, color: AMBER}}>
          выключить духовку.
        </Reveal>
      </div>
      <Ring time={time} top={700 - 175 * handoff} scale={1.1 + 0.06 * time / CUT.listen + 0.13 * handoff} heat/>
      <div style={{
        ...center, top: 980, fontSize: 173, fontWeight: 680, letterSpacing: -11,
        color: '#ffdbb5', opacity: (1 - exit) * tween(time, 0.08, 0.53),
        textShadow: '0 0 64px #ff842b50', fontVariantNumeric: 'tabular-nums',
      }}>
        180<span style={{fontSize: 91, verticalAlign: 'top', marginLeft: 9}}>°</span>
      </div>
      <div style={{
        ...center, ...row, top: 1218, gap: 15, color: AMBER, opacity: 1 - exit,
        fontSize: 23, fontWeight: 580, letterSpacing: 3.3,
      }}>
        <div style={{
          width: 8, height: 8, borderRadius: 8, background: AMBER,
          boxShadow: `0 0 ${14 + Math.sin(time * 13) * 7}px ${AMBER}`,
        }}/>
        НАГРЕВ
      </div>
    </AbsoluteFill>
  );
}

function Listening({time}: {time: number}) {
  const arrive = tween(time, CUT.listen, 3.68);
  const depart = tween(time, 8.39, CUT.result);
  const signalIn = tween(time, 4.32, 4.54);
  const signalOut = 1 - tween(time, 6.93, 7.25);
  const pulse = signalIn * signalOut * (0.52 + 0.28 * Math.sin(time * 23) + 0.16 * Math.sin(time * 41));
  const thinking = tween(time, 7.15, 7.44);
  return (
    <AbsoluteFill>
      <Backdrop time={time} heat={false}/>
      <div style={{
        opacity: (1 - depart) * arrive, position: 'absolute', top: 345, left: 0, width: '100%',
        textAlign: 'center', color: MINT, fontSize: 40, fontWeight: 560,
        letterSpacing: 0.3, transform: `translateY(${-22 * depart}px)`,
      }}>{time < 3.97 ? '«Тройка»' : thinking > 0.5 ? 'Разбираюсь…' : 'Слушаю…'}</div>
      <AbsoluteFill style={{opacity: (1 - arrive) * 0.64}}>
        <Ring time={time} top={525} scale={1.29 - arrive * 0.31} listening={pulse}/>
      </AbsoluteFill>
      <div style={{
        ...center, top: 474, width: 650, height: 650, opacity: arrive * (1 - 0.4 * depart),
        transform: `translateY(${-89 * depart}px) scale(${1.17 - 0.17 * arrive - 0.12 * depart})`,
      }}>
        <VoiceMark time={time} pulse={pulse} thinking={thinking}/>
      </div>
      <div style={{
        position: 'absolute', top: 1200, left: 91, width: 905, fontSize: 61,
        fontWeight: 630, lineHeight: 1.15, letterSpacing: -2.4, opacity: 1 - depart,
      }}>
        <Reveal time={time} start={4.34}>«Напомни через</Reveal>
        <Reveal time={time} start={5.05}><span style={{color: MINT}}>десять минут</span></Reveal>
        <Reveal time={time} start={5.64}>выключить духовку»</Reveal>
      </div>
    </AbsoluteFill>
  );
}

function VoiceMark({time, pulse, thinking}: {time: number; pulse: number; thinking: number}) {
  const expansion = 1 + 0.034 * Math.sin(time * 5) + 0.044 * pulse;
  const innerBeat = 0.85 + 0.13 * Math.sin(time * 6.8);
  const outerBeat = 0.52 + 0.22 * Math.sin(time * 6.8 - 1.4);
  return (
    <svg viewBox="0 0 112 112" width="650" height="650" aria-hidden>
      <g fill={GLOW}>
        <path d="M12 92V60C12 33.49 33.49 12 60 12H92a8 8 0 0 1 0 16H60c-17.673 0-32 14.327-32 32v32a8 8 0 0 1-16 0Z"
          opacity={outerBeat} transform={`translate(82 82) scale(${expansion}) translate(-82 -82)`}/>
        <path d="M40 92V68C40 52.536 52.536 40 68 40h24a8 8 0 0 1 0 16H68c-6.627 0-12 5.373-12 12v24a8 8 0 0 1-16 0Z"
          opacity={innerBeat} transform={`translate(82 82) scale(${1 + 0.66 * (expansion - 1)}) translate(-82 -82)`}/>
      </g>
      <circle cx="82" cy="82" r="17.35" fill="#0b0c10" fillOpacity=".86" stroke="#f4f5f7" strokeOpacity=".22" strokeWidth=".35"/>
      <g opacity={1 - thinking} fill={WHITE}>
        {Array.from({length: 5}, (_, i) => {
          const height = 3.5 + (3 + 10 * pulse) * (0.5 + 0.5 * Math.sin(time * 21 + i * 0.9));
          return <rect key={i} x={73.8 + 3.4 * i} y={82 - height / 2} width="2.8" height={height} rx="1.4"/>;
        })}
      </g>
      <circle cx="82" cy="82" r="7" pathLength="100" fill="none" stroke={WHITE} strokeWidth="1.1"
        strokeLinecap="round" strokeDasharray="58 42" opacity={thinking}
        transform={`rotate(${time * 205} 82 82)`}/>
    </svg>
  );
}

function Bell({size}: {size: number}) {
  return <svg width={size} height={size} viewBox="0 0 60 60" fill="none" aria-hidden>
    <path d="M30 52c3.7 0 6-2 6.5-5.1h-13A6.5 6.5 0 0 0 30 52Zm15.1-14.6c-2.4-2.6-3.2-5.5-3.2-12.4 0-6.2-3.7-10.7-9.4-12v-2.3a2.5 2.5 0 1 0-5 0V13c-5.7 1.3-9.4 5.8-9.4 12 0 6.9-.8 9.8-3.2 12.4l-2.2 2.4c-1.4 1.5-.4 4 1.7 4h31.2c2.1 0 3.1-2.5 1.7-4l-2.2-2.4Z" fill="currentColor"/>
  </svg>;
}

function Result({time}: {time: number}) {
  const appear = tween(time, CUT.result, 9.65);
  const pull = tween(time, 10.8, 11.92);
  const card = tween(time, 11.18, 12.03);
  const leave = tween(time, 13.78, CUT.brand);
  return (
    <AbsoluteFill>
      <Backdrop time={time} heat={false}/>
      <Ring time={time} top={346 + 218 * pull} scale={1.1 + 0.15 * pull}/>
      <div style={{
        ...center, top: 486 + 80 * pull, width: 490, padding: 11, borderRadius: 58,
        background: 'linear-gradient(145deg,#637b6d,#19241e 27%,#121713 67%,#44594d)',
        boxShadow: '0 50px 136px #000b, 0 0 0 1px #a2e7bd33',
        opacity: appear, transform: `translateY(${(1 - appear) * 140}px) scale(${0.91 + appear * 0.09 - pull * 0.08}) rotate(${-6 + 4 * appear - 3 * pull}deg)`,
      }}>
        <Img src={staticFile('android-home.png')} style={{
          display: 'block', width: '100%', borderRadius: 48,
          filter: `brightness(${1 - 0.53 * pull})`,
        }}/>
      </div>
      <div style={{
        position: 'absolute', left: 89, top: 320, opacity: 1 - pull,
        fontSize: 107, fontWeight: 740, letterSpacing: -7, color: MINT,
      }}>
        <Reveal time={time} start={8.8}>Готово.</Reveal>
      </div>
      <div style={{
        ...center, top: 724, width: 894, opacity: card * (1 - leave),
        transform: `translateY(${(1 - card) * 101 - leave * 55}px) scale(${0.95 + 0.05 * card})`,
      }}>
        <div style={{
          marginBottom: 24, color: '#d3f4df', fontWeight: 590, fontSize: 37,
          letterSpacing: -0.8, textShadow: '0 4px 16px #0c1512',
        }}>10 минут спустя</div>
        <div style={{
          ...row, gap: 30, borderRadius: 35, padding: '38px 39px',
          background: 'linear-gradient(135deg,#dcfae7,#94e2b4)', color: INK,
          boxShadow: '0 27px 88px #0008, 0 0 90px #57d19a22',
        }}>
          <div style={{
            display: 'grid', placeItems: 'center', width: 105, height: 105, flexShrink: 0,
            borderRadius: 27, color: MINT, background: '#183d2e',
            transform: `rotate(${Math.sin(time * 35) * (1 - tween(time, 11.23, 11.85)) * 9}deg)`,
          }}><Bell size={62}/></div>
          <div>
            <div style={{fontSize: 27, marginBottom: 8, fontWeight: 580, color: '#335e49'}}>Напоминание</div>
            <div style={{fontSize: 51, fontWeight: 690, letterSpacing: -2.2}}>Выключить духовку</div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
}

function EndCard({time}: {time: number}) {
  const entry = tween(time, CUT.brand, 14.95);
  return (
    <AbsoluteFill>
      <Backdrop time={time} heat={false}/>
      <div style={{...center, top: 522, opacity: 0.13 * (1 - entry), transform: 'scale(1.12)'}}>
        <Lines heat={false} time={time}/>
      </div>
      <div style={{
        ...center, top: 727, width: 860, textAlign: 'center',
        opacity: entry, transform: `translateY(${(1 - entry) * 65}px)`,
      }}>
        <Img src={staticFile('logo-ru-reverse.svg')} alt="Тройка" style={{width: 632, display: 'block', margin: '0 auto'}}/>
        <Reveal time={time} start={14.41} style={{
          marginTop: 39, color: '#daf3e4', fontSize: 47, fontWeight: 560, letterSpacing: -1.3,
        }}>Голосовая помощница</Reveal>
        <Reveal time={time} start={14.72} style={{
          marginTop: 28, color: '#b3cdbd', fontSize: 32, fontWeight: 490, letterSpacing: 1.6,
        }}>Android   ·   Windows</Reveal>
      </div>
    </AbsoluteFill>
  );
}

export function TroikaFilm({sound = true}: {sound?: boolean}) {
  const time = useCurrentFrame() / FPS;
  const next = time >= CUT.brand ? CUT.brand : time >= CUT.result ? CUT.result : CUT.listen;
  const flash = time >= CUT.listen ? 0.16 * (1 - tween(time, next, next + 0.24)) : 0;
  return (
    <AbsoluteFill style={{fontFamily: FONT, color: WHITE, background: INK}}>
      {time < CUT.listen && <Hook time={time}/>}
      {time >= CUT.listen && time < CUT.result && <Listening time={time}/>}
      {time >= CUT.result && time < CUT.brand && <Result time={time}/>}
      {time >= CUT.brand && <EndCard time={time}/>}
      <AbsoluteFill style={{background: '#d9ffec', opacity: flash, pointerEvents: 'none'}}/>
      {sound && <Audio src={staticFile('soundtrack.wav')}/>}
    </AbsoluteFill>
  );
}
