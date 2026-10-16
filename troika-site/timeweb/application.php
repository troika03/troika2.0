<?php
declare(strict_types=1);

// Product accounts remain on the existing API; Timeweb owns only the web adapter.
ini_set('display_errors', '0');
umask(0077);
const SITE_ORIGIN = 'https://cm444726.tw1.ru';
const API_ORIGIN = 'https://api.zhulebino-teahouse.ru';
const SESSION_COOKIE = '__Host-troika_session';
const PRIVATE_DIRECTORY = __DIR__ . '/../private';

function output(array $value, int $status = 200): never {
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($value, JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
    exit;
}
function failure(string $message, int $status): never { output(['error' => $message], $status); }
function configuration(): array {
    static $value;
    if ($value === null) {
        $value = json_decode((string)file_get_contents(PRIVATE_DIRECTORY . '/application.json'), true, 16, JSON_THROW_ON_ERROR);
        if (strlen($value['session_secret'] ?? '') < 64 || strlen($value['support_secret'] ?? '') < 64) throw new RuntimeException('Configuration unavailable');
    }
    return $value;
}
function encode64(string $value): string { return rtrim(strtr(base64_encode($value), '+/', '-_'), '='); }
function decode64(string $value): string {
    $decoded = base64_decode(strtr($value, '-_', '+/'), true);
    if ($decoded === false) throw new RuntimeException('Invalid encoding');
    return $decoded;
}
function encryptValue(string $plain, string $purpose): string {
    $key = hash('sha256', configuration()[$purpose === SESSION_COOKIE ? 'session_secret' : 'support_secret'], true);
    $iv = random_bytes(12);
    $cipher = openssl_encrypt($plain, 'aes-256-gcm', $key, OPENSSL_RAW_DATA, $iv, $tag, $purpose);
    if ($cipher === false) throw new RuntimeException('Encryption unavailable');
    return encode64($iv) . '.' . encode64($cipher . $tag);
}
function decryptValue(string $value, string $purpose): string {
    $parts = explode('.', $value);
    if (count($parts) !== 2) throw new RuntimeException('Invalid envelope');
    $iv = decode64($parts[0]); $data = decode64($parts[1]);
    if (strlen($iv) !== 12 || strlen($data) < 16) throw new RuntimeException('Invalid envelope');
    $key = hash('sha256', configuration()[$purpose === SESSION_COOKIE ? 'session_secret' : 'support_secret'], true);
    $plain = openssl_decrypt(substr($data, 0, -16), 'aes-256-gcm', $key, OPENSSL_RAW_DATA, $iv, substr($data, -16), $purpose);
    if ($plain === false) throw new RuntimeException('Invalid envelope');
    return $plain;
}
function readSession(): ?array {
    try {
        $value = $_COOKIE[SESSION_COOKIE] ?? '';
        if (!is_string($value) || strlen($value) > 3800 || $value === '') return null;
        $session = json_decode(decryptValue($value, SESSION_COOKIE), true, 16, JSON_THROW_ON_ERROR);
        return is_array($session) && ($session['refresh_expires_at'] ?? 0) > time()
            && is_string($session['access_token'] ?? null) && is_string($session['home_session_id'] ?? null) ? $session : null;
    } catch (Throwable) { return null; }
}
function sessionCookie(?array $session): void {
    $age = $session ? max(0, min(30 * 86400, (int)$session['refresh_expires_at'] - time())) : 0;
    $value = $session ? encryptValue(json_encode($session, JSON_THROW_ON_ERROR), SESSION_COOKIE) : '';
    header('Set-Cookie: ' . SESSION_COOKIE . '=' . $value . '; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=' . $age, false);
}
function requestBody(): array {
    static $body;
    if ($body !== null) return $body;
    if (!str_starts_with($_SERVER['CONTENT_TYPE'] ?? '', 'application/json')) failure('Ожидается JSON.', 400);
    if ((int)($_SERVER['CONTENT_LENGTH'] ?? 0) > 16000) failure('Слишком большой запрос.', 413);
    $raw = file_get_contents('php://input', false, null, 0, 16001);
    if ($raw === false || strlen($raw) > 16000) failure('Слишком большой запрос.', 413);
    try { $body = json_decode($raw, true, 32, JSON_THROW_ON_ERROR); }
    catch (Throwable) { failure('Некорректный запрос.', 400); }
    if (!is_array($body) || array_is_list($body)) failure('Некорректный запрос.', 400);
    return $body;
}
function database(): PDO {
    static $db;
    if (!$db) {
        $db = new PDO('sqlite:' . PRIVATE_DIRECTORY . '/support.sqlite', null, null, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION, PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC]);
        $db->exec('PRAGMA busy_timeout=5000; PRAGMA foreign_keys=ON;');
    }
    return $db;
}
function query(string $sql, array $arguments = []): PDOStatement {
    $statement = database()->prepare($sql); $statement->execute($arguments); return $statement;
}
function limited(string $operation, int $limit): bool {
    $key = hash_hmac('sha256', $operation . ':' . ($_SERVER['REMOTE_ADDR'] ?? 'local'), configuration()['session_secret']);
    $bucket = (int)floor(time() / 60);
    $db = database(); $db->exec('BEGIN IMMEDIATE');
    try {
        query('INSERT INTO site_rate_limits(key,bucket,used) VALUES(?,?,1) ON CONFLICT(key,bucket) DO UPDATE SET used=used+1', [$key, $bucket]);
        $used = (int)query('SELECT used FROM site_rate_limits WHERE key=? AND bucket=?', [$key, $bucket])->fetchColumn();
        query('DELETE FROM site_rate_limits WHERE bucket<?', [$bucket - 60]);
        $db->exec('COMMIT'); return $used > $limit;
    } catch (Throwable $error) { $db->exec('ROLLBACK'); throw $error; }
}
function upstream(string $path, ?array $session = null, string $method = 'GET', ?array $body = null, bool $export = false): array {
    if (!preg_match('~^/(?:health|v1/[A-Za-z0-9_/-]+)$~D', $path)) throw new RuntimeException('Invalid API route');
    $headers = ['Accept: application/json', 'Accept-Encoding: identity'];
    if ($session) $headers[] = 'Authorization: Bearer ' . $session['access_token'];
    if ($body !== null) $headers[] = 'Content-Type: application/json';
    $status = 0; $responseBody = ''; $length = 0;
    $curl = curl_init(API_ORIGIN . $path);
    curl_setopt_array($curl, [CURLOPT_CUSTOMREQUEST => $method, CURLOPT_HTTPHEADER => $headers,
        CURLOPT_FOLLOWLOCATION => false, CURLOPT_CONNECTTIMEOUT => 10, CURLOPT_TIMEOUT => $export ? 90 : 25,
        CURLOPT_USERAGENT => 'TroikaSite-Timeweb/1.0', CURLOPT_SSL_VERIFYPEER => true, CURLOPT_SSL_VERIFYHOST => 2,
        CURLOPT_HEADERFUNCTION => function ($curl, string $line) use (&$status, $export): int {
            if (preg_match('~^HTTP/\S+\s+(\d+)~', $line, $match)) {
                $status = (int)$match[1];
                if ($export && $status === 200) {
                    http_response_code(200); header('Content-Type: application/zip');
                    header('Content-Disposition: attachment; filename="Troika-account-export.zip"');
                }
            }
            return strlen($line);
        },
        CURLOPT_WRITEFUNCTION => function ($curl, string $data) use (&$responseBody, &$length, &$status, $export): int {
            $length += strlen($data);
            if ($length > ($export && $status === 200 ? 256 * 1024 * 1024 : 1024 * 1024)) return 0;
            if ($export && $status === 200) echo $data; else $responseBody .= $data;
            return strlen($data);
        }]);
    if ($body !== null) curl_setopt($curl, CURLOPT_POSTFIELDS, json_encode($body, JSON_THROW_ON_ERROR));
    $ok = curl_exec($curl); curl_close($curl);
    if ($ok === false || $status < 200 || ($status >= 300 && $status < 400)) throw new RuntimeException('API unavailable');
    if ($export && $status === 200) exit;
    $value = json_decode($responseBody, true, 64, JSON_THROW_ON_ERROR);
    if (!is_array($value)) throw new RuntimeException('Invalid API response');
    return [$status, $value];
}
function uuid(): string {
    $bytes = random_bytes(16); $bytes[6] = chr((ord($bytes[6]) & 15) | 64); $bytes[8] = chr((ord($bytes[8]) & 63) | 128);
    $h = bin2hex($bytes); return substr($h,0,8).'-'.substr($h,8,4).'-'.substr($h,12,4).'-'.substr($h,16,4).'-'.substr($h,20);
}
function deleteSupport(string $owner): void { query('DELETE FROM support_tickets WHERE owner_key=?', [$owner]); }
function downloads(string $path, string $method): never {
    if (!in_array($method, ['GET','HEAD'], true)) failure('Метод не поддерживается.', 405);
    $releases = json_decode((string)file_get_contents(PRIVATE_DIRECTORY . '/releases.json'), true, 16, JSON_THROW_ON_ERROR);
    foreach ($releases as $release) {
        if (($release['url'] ?? '') !== $path) continue;
        $file = PRIVATE_DIRECTORY . '/releases/' . basename($release['filename']);
        if (!is_file($file) || filesize($file) !== $release['size']) failure('Файл временно недоступен.', 503);
        $size = $release['size']; $start = 0; $end = $size - 1;
        if (isset($_SERVER['HTTP_RANGE'])) {
            if (!preg_match('~^bytes=(\d*)-(\d*)$~D', $_SERVER['HTTP_RANGE'], $m) || ($m[1] === '' && $m[2] === '')) { header('Content-Range: bytes */'.$size); failure('Неверный диапазон.',416); }
            if ($m[1] === '') $start = max(0,$size-(int)$m[2]); else { $start = (int)$m[1]; if ($m[2] !== '') $end = min($end,(int)$m[2]); }
            if ($start > $end || $start >= $size) { header('Content-Range: bytes */'.$size); failure('Неверный диапазон.',416); }
            http_response_code(206); header("Content-Range: bytes $start-$end/$size");
        }
        header('Content-Type: application/octet-stream'); header('Content-Disposition: attachment; filename="'.$release['filename'].'"');
        header('Content-Length: '.($end-$start+1)); header('Accept-Ranges: bytes'); header('ETag: "'.$release['sha256'].'"');
        header('Cache-Control: public, max-age=31536000, immutable');
        if ($method === 'HEAD') exit;
        $handle = fopen($file,'rb'); fseek($handle,$start); $remaining = $end-$start+1;
        while ($remaining > 0 && !feof($handle) && !connection_aborted()) { $chunk = fread($handle,min(1048576,$remaining)); if ($chunk === false || $chunk === '') break; echo $chunk; $remaining -= strlen($chunk); }
        fclose($handle); exit;
    }
    failure('Файл не найден.',404);
}
function runSite(): never {
    header('X-Content-Type-Options: nosniff'); header('Referrer-Policy: same-origin'); header('Cache-Control: no-store');
    $method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
    $path = parse_url($_SERVER['REQUEST_URI'] ?? '', PHP_URL_PATH);
    if ($path === '/transfer.php' && is_string($_GET['download'] ?? null)) $path = $_GET['download'];
    if (!is_string($path)) failure('Нет такого адреса.',404);
    if (!in_array($method,['GET','HEAD','POST','PUT','PATCH','DELETE'],true)) failure('Метод не поддерживается.',405);
    if (!in_array($method,['GET','HEAD'],true) && ($_SERVER['HTTP_ORIGIN'] ?? '') !== SITE_ORIGIN) failure('Источник запроса не разрешён.',403);
    if (str_starts_with($path,'/downloads/')) downloads($path,$method);
    if ($path === '/api/status' && $method === 'GET') {
        $start = microtime(true); $available = false;
        try { [$status,$data] = upstream('/health'); $available = $status === 200 && ($data['status'] ?? '') === 'ok'; } catch (Throwable) {}
        output(['available'=>$available,'checked_at'=>gmdate('c'),'latency_ms'=>(int)round((microtime(true)-$start)*1000)]);
    }
    if ($path === '/api/releases' && $method === 'GET') output(['releases'=>json_decode((string)file_get_contents(PRIVATE_DIRECTORY.'/releases.json'),true,16,JSON_THROW_ON_ERROR)]);
    if (str_starts_with($path,'/api/admin/') || str_starts_with($path,'/api/support-admin')) failure('Такого действия нет.',404);
    $session = readSession();
    if ($path === '/api/session' && $method === 'GET') output(['signed_in'=>$session!==null,'email'=>$session['email']??null,'support_admin'=>false]);
    if (in_array($path,['/api/auth/login','/api/auth/register'],true) && $method === 'POST') {
        if (limited('auth',8)) failure('Слишком много попыток. Попробуйте через минуту.',429);
        $body = requestBody(); $email = is_string($body['email']??null) ? strtolower(trim($body['email'])) : '';
        if (!filter_var($email,FILTER_VALIDATE_EMAIL) || strlen($email)>254 || !is_string($body['password']??null) || strlen($body['password'])<10 || strlen($body['password'])>128) failure('Проверьте почту и пароль: от 10 до 128 символов.',400);
        if ($path === '/api/auth/register' && ($body['consent']??null)!==true) failure('Подтвердите условия и обработку данных.',400);
        [$status,$data] = upstream(str_replace('/api/','/v1/',$path),null,'POST',['email'=>$email,'password'=>$body['password'],'device_name'=>'Сайт Тройки','platform'=>'web']);
        if ($status>=400) failure($status===409?'Аккаунт с этой почтой уже есть. Войдите.':($status===401?'Неверная почта или пароль.':'Вход недоступен. Попробуйте позже.'),$status);
        $session = ['access_token'=>$data['access_token']??$data['token']??null,'refresh_token'=>$data['refresh_token']??null,'refresh_expires_at'=>$data['refresh_expires_at']??null,'home_session_id'=>$data['home_session_id']??null,'email'=>$email];
        if (!$session['access_token'] || !$session['refresh_token'] || !$session['home_session_id'] || !is_numeric($session['refresh_expires_at'])) failure('Сервер не поддерживает безопасный веб-вход.',503);
        sessionCookie($session); output(['signed_in'=>true,'email'=>$email],$status);
    }
    if (!$session) failure('Войдите в аккаунт.',401);
    if ($path === '/api/auth/refresh' && $method === 'POST') {
        [$status,$data] = upstream('/v1/auth/refresh',null,'POST',['refresh_token'=>$session['refresh_token']]);
        if ($status>=400) { if ($status===401) sessionCookie(null); failure('Сеанс завершён. Войдите снова.',$status); }
        $session['access_token']=$data['access_token']??$data['token']; $session['refresh_token']=$data['refresh_token']; $session['refresh_expires_at']=$data['refresh_expires_at'];
        sessionCookie($session); output(['signed_in'=>true]);
    }
    if ($path === '/api/auth/logout' && $method === 'POST') {
        [$status,$data] = upstream('/v1/account/devices',$session);
        if ($status!==401) {
            if ($status!==200) failure('Не удалось завершить сеанс. Повторите выход.',503);
            $current = array_values(array_filter($data['devices']??[],fn($d)=>!empty($d['current'])&&($d['status']??'')==='active'));
            if (!$current || !preg_match('~^[A-Za-z0-9_-]{1,100}$~D',$current[0]['id'])) failure('Не удалось определить текущее устройство.',503);
            [$status] = upstream('/v1/account/devices/'.$current[0]['id'],$session,'DELETE');
            if ($status>=400) failure('Не удалось отозвать доступ. Повторите выход.',$status);
        }
        sessionCookie(null); output(['signed_in'=>false]);
    }
    $owner = hash('sha256',$session['home_session_id']);
    if ($path === '/api/support' || preg_match('~^/api/support/[a-f0-9-]{36}$~D',$path)) {
        [$status] = upstream('/v1/subscription',$session); if ($status!==200) failure('Войдите снова.',401);
        if ($path === '/api/support' && $method === 'GET') {
            $tickets = query('SELECT id,category,subject,message,status,created_at FROM support_tickets WHERE owner_key=? ORDER BY created_at DESC LIMIT 100',[$owner])->fetchAll();
            foreach ($tickets as &$ticket) {
                foreach (['subject','message'] as $field) $ticket[$field]=decryptValue($ticket[$field],'support.'.$field);
                $ticket['replies']=query('SELECT author,message,created_at FROM support_replies WHERE ticket_id=? ORDER BY created_at LIMIT 1000',[$ticket['id']])->fetchAll();
                foreach ($ticket['replies'] as &$reply) $reply['message']=decryptValue($reply['message'],'support.reply'); unset($reply);
            } unset($ticket); output(['tickets'=>$tickets]);
        }
        if ($path === '/api/support' && $method === 'POST') {
            if (limited('support',3)) failure('Подождите минуту перед новым обращением.',429);
            $body=requestBody();
            if (!in_array($body['category']??'', ['technical','account','billing','security'],true) || !is_string($body['subject']??null) || mb_strlen(trim($body['subject']))<3 || mb_strlen($body['subject'])>150 || !is_string($body['message']??null) || mb_strlen(trim($body['message']))<10 || mb_strlen($body['message'])>5000) failure('Тема: 3–150 символов. Описание: 10–5000 символов.',400);
            $id=uuid(); $now=(int)round(microtime(true)*1000);
            query('INSERT INTO support_tickets(id,owner_key,email,category,subject,message,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',[$id,$owner,encryptValue($session['email'],'support.email'),$body['category'],encryptValue(trim($body['subject']),'support.subject'),encryptValue(trim($body['message']),'support.message'),$now,$now]);
            output(['id'=>$id,'saved'=>true],201);
        }
        if ($method==='DELETE' && $path!=='/api/support') {
            $id=basename($path); if (!query('SELECT id FROM support_tickets WHERE id=? AND owner_key=?',[$id,$owner])->fetch()) failure('Обращение не найдено.',404);
            query('DELETE FROM support_tickets WHERE id=? AND owner_key=?',[$id,$owner]); output(['deleted'=>true]);
        }
        failure('Такого действия нет.',404);
    }
    $routes=['/api/subscription'=>['/v1/subscription',['GET']],'/api/devices'=>['/v1/account/devices',['GET']],'/api/export'=>['/v1/account/export',['GET']],'/api/account'=>['/v1/account',['DELETE']],'/api/logout-all'=>['/v1/auth/logout-all',['POST']],'/api/memories'=>['/v1/memories',['GET','POST']],'/api/memory-preferences'=>['/v1/memory-preferences',['GET','PUT']],'/api/billing'=>['/v1/billing',['GET']],'/api/billing/checkout'=>['/v1/billing/checkout',['POST']]];
    $target=isset($routes[$path])&&in_array($method,$routes[$path][1],true)?$routes[$path][0]:null;
    if (preg_match('~^/api/(devices|memories|billing)/[A-Za-z0-9_-]{1,100}$~D',$path,$m)) {
        if (($m[1]==='devices'&&$method==='DELETE')||($m[1]==='memories'&&in_array($method,['PATCH','DELETE'],true))||($m[1]==='billing'&&$method==='GET')) $target=str_replace('/api/',$m[1]==='devices'?'/v1/account/':'/v1/',$path);
    }
    if (!$target) failure('Такого действия нет.',404);
    if ($path==='/api/billing/checkout') failure('Оплата ещё не подключена.',503);
    $body=in_array($method,['POST','PUT','PATCH','DELETE'],true)&&((int)($_SERVER['CONTENT_LENGTH']??0)>0||isset($_SERVER['CONTENT_TYPE']))?requestBody():null;
    if ($path==='/api/account'&&($body['confirmation']??'')!=='DELETE_MY_ACCOUNT') failure('Нужно явное подтверждение удаления.',400);
    [$status,$data]=upstream($target,$session,$method,$body,$path==='/api/export');
    if ($path==='/api/billing'&&$status<400) $data['enabled']=false;
    if ($status<400&&in_array($path,['/api/account','/api/logout-all'],true)) { if ($path==='/api/account') deleteSupport($owner); sessionCookie(null); }
    output($data,$status);
}
