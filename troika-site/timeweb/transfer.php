<?php
declare(strict_types=1);
require __DIR__ . '/application.php';
try { runSite(); }
catch (Throwable) {
    if (!headers_sent()) failure('Сервис временно недоступен. Повторите позже.', 502);
}