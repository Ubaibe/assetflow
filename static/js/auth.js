const AssetFlowWalletAuth = (() => {
  let connectedAddress = null;

  async function connectWallet() {
    if (!window.ethereum) {
      throw new Error("No EIP-1193 wallet detected");
    }
    const accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
    if (!accounts || accounts.length === 0) {
      throw new Error("Wallet connection rejected");
    }
    connectedAddress = accounts[0];
    return connectedAddress;
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

  async function authenticate() {
    try {
      const address = await connectWallet();
      const challenge = await requestChallenge(address);
      const signature = await signMessage(challenge.message);
      const result = await verifySignature(address, signature, challenge.challenge_id);
      return { ...result, shortened_address: shortenAddress(address) };
    } catch (error) {
      return { error: error.message };
    }
  }

  return {
    connectWallet,
    requestChallenge,
    signMessage,
    verifySignature,
    logout,
    shortenAddress,
    authenticate,
  };
})();
