// Display metadata for accounts that appear in the bundled trade data
// (src/importedData.js). Keys must match trade.account exactly; see
// tests/accounts.test.mjs. Balances are not in the exported data, so none
// are set here: the UI shows "Data only" rather than an invented number.
export const INITIAL_ACCOUNTS={
 "XM Demo":{platform:"MT5",status:"DEMO"},
 "ICMarkets Demo":{platform:"MT5",status:"DEMO"}
};
