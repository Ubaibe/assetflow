const AssetFlowWalletAuth = (() => {
  let connectedAddress = null;

  function getChainId() {
    if (!window.ethereum) return null;
    return window.ethereum.request({ method: "eth_chainId" });
  }

  async function connectWallet() {
    if (!window.ethereum) {
      throw new Error(
        "No compatible EVM wallet detected. Please install MetaMask or another compatible wallet."
      );
    }
    const accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
    if (!accounts || accounts.length === 0) {
      throw new Error("Wallet connection was cancelled.");
    }
    connectedAddress = accounts[0];
    return connectedAddress;
  }

  async function checkNetwork(expectedChainId) {
    if (!window.ethereum || !expectedChainId) return true;
    const chainId = await getChainId();
    if (!chainId) return true;
    const expected = typeof expectedChainId === "number" ? expectedChainId : parseInt(expectedChainId, 10);
    const actual = typeof chainId === "string" ? parseInt(chainId, 16) : chainId;
    if (actual !== expected) {
      throw new Error("Please switch your wallet to BOT Chain Testnet.");
    }
    return true;
  }

  async function requestChallenge(address) {
    const response = await fetch("/auth/challenge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ wallet_address: address }),
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || "Failed to request challenge");
    }
    return response.json();
  }

  async function signMessage(message) {
    if (!window.ethereum || !connectedAddress) {
      throw new Error("Wallet not connected");
    }
    const signature = await window.ethereum.request({
      method: "personal_sign",
      params: [message, connectedAddress],
    });
    return signature;
  }

  async function verifySignature(address, signature, challengeId) {
    const response = await fetch("/auth/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        wallet_address: address,
        signature,
        challenge_id: challengeId,
      }),
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || "Authentication failed");
    }
    return response.json();
  }

  async function logout() {
    const response = await fetch("/auth/logout", { method: "POST" });
    connectedAddress = null;
    return response.json();
  }

  function shortenAddress(address) {
    if (!address || address.length < 10) return address;
    return `${address.slice(0, 6)}...${address.slice(-4)}`;
  }

  return {
    connectWallet,
    checkNetwork,
    requestChallenge,
    signMessage,
    verifySignature,
    logout,
    shortenAddress,
  };
})();
