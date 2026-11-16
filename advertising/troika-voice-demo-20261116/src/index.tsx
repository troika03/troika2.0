import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {TroikaFilm, FPS, LENGTH} from './troika';
import './type.css';

const Root = () => (
  <Composition
    id="Troika"
    component={TroikaFilm}
    width={1080}
    height={1920}
    fps={FPS}
    durationInFrames={LENGTH * FPS}
  />
);

registerRoot(Root);
