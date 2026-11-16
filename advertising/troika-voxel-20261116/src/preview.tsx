import React, {useLayoutEffect, useRef} from 'react';
import {createRoot} from 'react-dom/client';
import {Player, PlayerRef} from '@remotion/player';
import {TroikaFilm} from './troika';
import {FPS, FRAMES} from './beats';
import './type.css';

const params = new URLSearchParams(location.search);
const capture = params.has('capture');

declare global {
  interface Window {
    seek?: (frame: number) => void;
  }
}

function Preview() {
  const player = useRef<PlayerRef>(null);
  useLayoutEffect(() => {
    window.seek = (frame) => player.current?.seekTo(frame);
  }, []);
  return (
    <Player
      ref={player}
      component={TroikaFilm}
      compositionWidth={1080}
      compositionHeight={1920}
      durationInFrames={FRAMES}
      fps={FPS}
      controls={!capture}
      loop={!capture}
      style={capture
        ? {width: '100vw', height: '100vh'}
        : {height: '100vh', maxWidth: '100vw', aspectRatio: '9 / 16', margin: 'auto'}}
    />
  );
}

createRoot(document.getElementById('root')!).render(<Preview/>);
