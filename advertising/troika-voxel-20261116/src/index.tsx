import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {TroikaFilm} from './troika';
import {FPS, FRAMES} from './beats';
import './type.css';

const Root = () => (
  <Composition
    id="Troika"
    component={TroikaFilm}
    width={1080}
    height={1920}
    fps={FPS}
    durationInFrames={FRAMES}
  />
);

registerRoot(Root);
