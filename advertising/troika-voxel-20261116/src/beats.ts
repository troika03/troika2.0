export const FPS = 30;

export type View = 'person' | 'assistant' | 'light' | 'result' | 'cover' | 'wide';
export type Beat = {
  start: number;
  view: View;
  speaker?: 'human' | 'troika';
  lines?: string[];
  reaction?: 'quick' | 'question' | 'ask' | 'smirk' | 'punch' | 'deadpan' | 'caught' | 'late';
  insert?: 'light' | 'source' | 'slides' | 'research' | 'deck';
};

const fiveMinutes: Beat[] = [
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

const deadline: Beat[] = [
  {start: 0, view: 'person', speaker: 'human', lines: ['Тройка, презентацию надо было', 'сдать вчера.'], reaction: 'late'},
  {start: 2.93, view: 'assistant', speaker: 'troika', lines: ['Какая тема?'], reaction: 'quick'},
  {start: 4.67, view: 'person', speaker: 'human', lines: ['Как перестать всё откладывать.']},
  {start: 7.33, view: 'assistant', speaker: 'troika', lines: ['Сильное начало.'], reaction: 'deadpan'},
  {start: 9.27, view: 'person', speaker: 'human', lines: ['Найди источник.', 'И собери три слайда.'], reaction: 'ask'},
  {start: 12.33, view: 'result', speaker: 'troika', lines: ['Нашла. Начни с маленького шага.'], insert: 'research'},
  {start: 15.60, view: 'result', speaker: 'troika', lines: ['Три слайда готовы.'], insert: 'deck'},
  {start: 18.80, view: 'person', speaker: 'human', lines: ['Добавь пример из жизни.'], reaction: 'smirk'},
  {start: 21.27, view: 'assistant', speaker: 'troika', lines: ['Ты уже на титульном.'], reaction: 'punch'},
  {start: 23.47, view: 'cover'},
  {start: 25.30, view: 'person', reaction: 'caught'},
  {start: 26.67, view: 'wide'},
];

export const episodes = {
  'five-minutes': {beats: fiveMinutes, frames: 984, composition: 'Troika'},
  deadline: {beats: deadline, frames: 882, composition: 'TroikaDeadline'},
};

export type Episode = keyof typeof episodes;
export const defaultEpisode: Episode = 'five-minutes';

export function beatAt(time: number, episode: Episode) {
  const {beats, frames} = episodes[episode];
  const index = beats.findLastIndex(beat => beat.start <= time);
  return {beat: beats[index], end: beats[index + 1]?.start ?? frames / FPS};
}
