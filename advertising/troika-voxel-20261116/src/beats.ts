export const FPS = 30;
export const FRAMES = 984;
export const LENGTH = FRAMES / FPS;

export type View = 'person' | 'assistant' | 'light' | 'result' | 'wide';
export type Beat = {
  start: number;
  view: View;
  speaker?: 'human' | 'troika';
  lines?: string[];
  reaction?: 'quick' | 'question' | 'ask' | 'smirk' | 'punch';
  insert?: 'light' | 'source' | 'slides';
};

export const beats: Beat[] = [
  {start: 0, view: 'person', speaker: 'human', lines: ['Тройка, до созвона', 'пять минут.']},
  {start: 2.74, view: 'assistant', speaker: 'troika', lines: ['Говори, пока четыре.'], reaction: 'quick'},
  {start: 5.04, view: 'person', speaker: 'human', lines: ['Включи фонарик.', 'Флешка под столом.'], reaction: 'ask'},
  {start: 8.02, view: 'light', speaker: 'troika', lines: ['Свет есть.'], insert: 'light'},
  {start: 10.35, view: 'person', speaker: 'human', lines: ['Как записать экран в Windows?', 'Найди источник.'], reaction: 'question'},
  {start: 13.96, view: 'result', speaker: 'troika', lines: ['Вот справка Microsoft.', 'Win + Shift + R.'], insert: 'source'},
  {start: 17.58, view: 'person', speaker: 'human', lines: ['Собери по ней три слайда.'], reaction: 'ask'},
  {start: 20.08, view: 'result', speaker: 'troika', lines: ['Готово. Три слайда, один файл.'], insert: 'slides'},
  {start: 23.45, view: 'person', speaker: 'human', lines: ['А выступишь за меня?'], reaction: 'smirk'},
  {start: 25.94, view: 'assistant', speaker: 'troika', lines: ['Тебя в PPTX не упаковать.'], reaction: 'punch'},
  {start: 29.31, view: 'wide'},
];

export function beatAt(time: number) {
  const index = beats.findLastIndex(beat => beat.start <= time);
  return {beat: beats[index], index, end: beats[index + 1]?.start ?? LENGTH};
}
