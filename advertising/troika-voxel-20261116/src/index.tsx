import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {TroikaFilm} from './troika';
import {episodes, type Episode, FPS} from './beats';
import './type.css';

const Root = () => <>
  {Object.entries(episodes).map(([episode, spec]) => (
    <Composition
      key={episode}
      id={spec.composition}
      component={TroikaFilm}
      defaultProps={{episode: episode as Episode}}
      width={1080}
      height={1920}
      fps={FPS}
      durationInFrames={spec.frames}
    />
  ))}
  <Composition
    id="TroikaDeadlineVoiced"
    component={TroikaFilm}
    defaultProps={{episode: 'deadline', voiced: true}}
    width={1080}
    height={1920}
    fps={FPS}
    durationInFrames={episodes.deadline.frames}
  />
</>;

registerRoot(Root);
