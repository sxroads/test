<!doctype html>
<html>
<head>
<title>Sanal POS entegrasyonu örnek PHP sayfamız</title>
<meta charset="utf-8">
</head>
<body>

<?php
// sx değeriniz size verilecektir
$sx="118591467|bScbGDYCtPf7SS1N6PQ6/+58rFhW1WpsWINqvkJFaJlu6bMH2tgPKDQtjeA5vClpzJP24uA0vx7OX53cP3SgUspa4EvYix+1C3aXe++8glUvu9Oyyj3v300p5NP7ro/9K57Zcw==";
$merchantSecretKey="_YckdxUbv4vrnMUZ6VQsr"; // size özel - special to you
$successUrl="https://paynkolay.com.tr/test/success";
$failUrl="https://paynkolay.com.tr/test/fail";
$amount="5.00";
$currencyCode="949";
$clientRefCode="2352345";
$use3D="true";
$rnd = date("d.m.Y H:i:s");
$agentCode="1236";
$detail="false";
$transactionType="SALES";
$customerKey = "";
$instalments = "";
$hashstr = $sx . "|" . $clientRefCode . "|" . $amount . "|" . $successUrl . "|" . $failUrl . "|" . $rnd . "|" . $customerKey . "|" . $merchantSecretKey;

$hash = mb_convert_encoding($hashstr, 'UTF-8');
$hashedBytes = hash("sha512", $hash, true);
$hashDataV2 = base64_encode($hashedBytes);

function getClientIpAddress(): string
{
    // A list of headers to check in order of priority
    $headers = [
        'HTTP_CLIENT_IP',
        'HTTP_X_FORWARDED_FOR',
        'HTTP_X_FORWARDED',
        'HTTP_X_CLUSTER_CLIENT_IP',
        'HTTP_FORWARDED_FOR',
        'HTTP_FORWARDED',
        'REMOTE_ADDR'
    ];

    foreach ($headers as $header) {
        if (isset($_SERVER[$header])) {
            // HTTP_X_FORWARDED_FOR can contain a comma-separated list of IPs.
            // The first one is the original client IP.
            $ipList = explode(',', $_SERVER[$header]);
            $ip = trim($ipList[0]);

            // Validate the IP address
            if (filter_var($ip, FILTER_VALIDATE_IP)) {
                return $ip;
            }
        }
    }

    return 'UNKNOWN';
}

// How to use the function
$cardHolderIP = getClientIpAddress();

?>

<!-- Canlı ortam için form action linki "https://paynkolay.nkolayislem.com.tr/Vpos" olmalıdır. -->
<form method="post" action="https://paynkolaytest.nkolayislem.com.tr/Vpos">
  <input type="hidden" name="sx" value="<?= $sx ?>">
  <input type="hidden" name="successUrl" value="<?= $successUrl ?>">
  <input type="hidden" name="failUrl" value="<?= $failUrl ?>">
  <input type="hidden" name="amount" value="<?= $amount ?>">
  <input type="hidden" name="currencyCode" value="<?= $currencyCode ?>">
  <input type="hidden" name="clientRefCode" value="<?= $clientRefCode ?>">
  <input type="hidden" name="use3D" value="<?= $use3D ?>">
  <input type="hidden" name="rnd" value="<?= $rnd ?>">
  <input type="hidden" name="agentCode" value="<?= $agentCode ?>">
  <input type="hidden" name="transactionType" value="<?= $transactionType ?>">
  <input type="hidden" name="hashDataV2" value="<?= $hashDataV2 ?>">
  <input type="hidden" name="cardHolderIP" value="<?= $cardHolderIP ?>">
  <input type="hidden" name="instalments" value="<?= $instalments ?>">
  <input type="submit" value="Gönder" />
</form>

</body>
</html>
