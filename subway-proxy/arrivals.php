<?php
header('Content-Type: application/json');

$direction = isset($_GET['direction']) ? strtoupper($_GET['direction']) : 'S';
if ($direction !== 'N' && $direction !== 'S') {
    http_response_code(400);
    echo json_encode(['error' => 'direction must be N or S']);
    exit;
}

$script = __DIR__ . '/fetch_arrivals.py';
$output = shell_exec("python3 " . escapeshellarg($script) . " " . escapeshellarg($direction) . " 2>&1");

if ($output === null) {
    http_response_code(500);
    echo json_encode(['error' => 'failed to execute python script']);
    exit;
}

echo $output;
