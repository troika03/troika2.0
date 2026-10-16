<?php
declare(strict_types=1);
// Run through the authenticated hosting console. Never expose this file in public_html.
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }
require __DIR__ . '/public_html/application.php';
$operation = $argv[1] ?? 'list';
$id = $argv[2] ?? '';
if ($operation === 'list') {
    echo json_encode(query('SELECT id,category,status,created_at,updated_at FROM support_tickets ORDER BY created_at DESC LIMIT 100')->fetchAll(), JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR) . "\n";
    exit;
}
if (!preg_match('~^[a-f0-9-]{36}$~D', $id)) throw new RuntimeException('A ticket UUID is required');
$ticket = query('SELECT * FROM support_tickets WHERE id=?', [$id])->fetch();
if (!$ticket) throw new RuntimeException('Ticket not found');
if ($operation === 'show') {
    unset($ticket['owner_key']);
    foreach (['email','subject','message'] as $field) $ticket[$field] = decryptValue($ticket[$field], 'support.' . $field);
    $ticket['replies'] = query('SELECT author,message,created_at FROM support_replies WHERE ticket_id=? ORDER BY created_at', [$id])->fetchAll();
    foreach ($ticket['replies'] as &$reply) $reply['message'] = decryptValue($reply['message'], 'support.reply');
    echo json_encode($ticket, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR) . "\n";
    exit;
}
if ($operation !== 'reply') throw new RuntimeException('Use list, show UUID, or reply UUID with JSON on stdin');
$input = json_decode((string)stream_get_contents(STDIN, 20001), true, 16, JSON_THROW_ON_ERROR);
$message = $input['message'] ?? null;
$status = $input['status'] ?? 'closed';
if (!is_string($message) || mb_strlen(trim($message)) < 1 || mb_strlen($message) > 5000 || !in_array($status, ['open','closed'], true)) throw new RuntimeException('Invalid reply or status');
$now = (int)round(microtime(true) * 1000);
$db = database();
$db->beginTransaction();
try {
    query('INSERT INTO support_replies(id,ticket_id,author,message,created_at) VALUES(?,?,?,?,?)', [uuid(), $id, 'support', encryptValue(trim($message), 'support.reply'), $now]);
    query('UPDATE support_tickets SET status=?,updated_at=? WHERE id=?', [$status, $now, $id]);
    $db->commit();
} catch (Throwable $error) { $db->rollBack(); throw $error; }
echo "Reply saved.\n";
