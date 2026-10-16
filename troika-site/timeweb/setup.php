<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }
umask(0077);
$private = __DIR__ . '/private';
if (!is_dir($private)) mkdir($private, 0700, true);
chmod($private, 0700);
$config = $private . '/application.json';
if (!is_file($config)) {
    $handle = fopen($config, 'x');
    if (!$handle) throw new RuntimeException('Cannot create configuration');
    fwrite($handle, json_encode(['session_secret' => bin2hex(random_bytes(48)), 'support_secret' => bin2hex(random_bytes(48))], JSON_THROW_ON_ERROR));
    fclose($handle);
}
chmod($config, 0600);
require __DIR__ . '/public_html/application.php';
configuration();
database()->exec((string)file_get_contents(__DIR__ . '/support-schema.sql'));
chmod($private . '/support.sqlite', 0600);
$specifications = [
    'android' => ['Troika-2026-10-12.apk', 114810601, '0de9cef65d108595273b9dba1aabe41538e08214595e37f9bc2ac42661a3e959'],
    'windows' => ['Troika-2026-10-12.zip', 108460, 'c92ea1dea3575c20e835cb2ba1362d625d6b713b01b6f4f8fe8beb8b981babd7'],
];
$releases = [];
foreach ($specifications as $platform => [$filename, $size, $sha256]) {
    $file = $private . '/releases/' . $filename;
    if (!is_file($file) || filesize($file) !== $size || !hash_equals($sha256, hash_file('sha256', $file))) throw new RuntimeException('Installer verification failed: ' . $platform);
    chmod($file, 0600);
    $releases[$platform] = ['platform' => $platform, 'version' => '2026-10-12', 'filename' => $filename, 'size' => $size, 'sha256' => $sha256, 'url' => '/downloads/' . $platform . '/' . $sha256 . '/' . $filename, 'published_at' => gmdate('c', (int)filemtime($file))];
}
file_put_contents($private . '/releases.json', json_encode($releases, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR), LOCK_EX);
chmod($private . '/releases.json', 0600);
echo "Timeweb application ready; private configuration, SQLite and both verified installers available.\n";
