import React, {useLayoutEffect, useRef} from 'react';
import {createRoot} from 'react-dom/client';
import {Player, PlayerRef} from '@remotion/player';
import {TroikaFilm} from './troika';
import {defaultEpisode, episodes, type Episode, FPS} from './beats';
import './type.css';

const params = new URLSearchParams(location.search);
const capture = params.has('capture');
const requested = params.get('episode');
const episode = requested && Object.hasOwn(episodes, requested) ? requested as Episode : defaultEpisode;
const voiced = episode === 'deadline' && params.has('voiced');

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
      inputProps={{episode, voiced, mute: capture}}
      compositionWidth={1080}
      compositionHeight={1920}
      durationInFrames={episodes[episode].frames}
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
