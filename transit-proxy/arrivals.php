<?php
header('Content-Type: application/json');

// Downtown/southbound only in transit mode
$direction = 'S';

$script = __DIR__ . '/fetch_arrivals.py';
$output = shell_exec("python3 " . escapeshellarg($script) . " " . escapeshellarg($direction) . " 2>&1");

if ($output === null) {
    http_response_code(500);
    echo json_encode(['error' => 'failed to execute python script']);
    exit;
}

echo $output;
