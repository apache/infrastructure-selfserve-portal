/*
 Licensed to the Apache Software Foundation (ASF) under one or more
 contributor license agreements.  See the NOTICE file distributed with
 this work for additional information regarding copyright ownership.
 The ASF licenses this file to You under the Apache License, Version 2.0
 (the "License"); you may not use this file except in compliance with
 the License.  You may obtain a copy of the License at

     http://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
*/

/*
Main script library for the web-based user interface for selfserve.apache.org
*/

const LIB_NAME = '[Selfserve Platform]';

// Standard console logging for debugging purposes
/* eslint no-console: ["error", { allow: ["debug", "info", "warn", "error"] }] */
function log(msg, level = 'info') {
  if (level === 'info') console.info(LIB_NAME, msg);
}

// Simple UUID generator for debugging and oauth requests
function uuid() {
  return Math.random().toString(20).substring(2, 8)
      + Math.random().toString(20).substring(2, 8)
      + Math.random().toString(20).substring(2, 8);
}

// Converts dictionaries to FormData
function toFormData(params) {
  if (!params) return null; // No form data? Return null then.
  if (params instanceof FormData) return params; // Already a FormData object? Just return it then.
  if (params instanceof File) return params; // A File object will also suffice for Fetch.
  // Otherwise, construct from dictionary and return.
  const fd = new FormData();
  Object.entries(params).forEach(([key, value]) => fd.append(key, value));
  return fd;
}

// Basic check for whether sessionStorage is supported or not
function sessionStorageSupported() {
  try {
    const storage = window.sessionStorage;
    storage.setItem('test', 'test');
    storage.removeItem('test');
    return true;
  } catch (e) {
    return false;
  }
}

// Basic GET HTTP call
async function GET(url, params, method = 'GET') {
  const xhrID = uuid();
  const parameters = params || {}; // We want a dict here
  const headers = new Headers();
  headers.append('X-Selfserve-WebUI', 'yes'); // Inform the backend that we will not accept a Realm response
  if (parameters.json) headers.append('Content-Type', 'application/json');

  const data = parameters.json ? JSON.stringify(parameters.json) : toFormData(parameters.data);
  log(`[${xhrID}] Sending ${method} XHR to URL ${url}`);
  const response = await fetch(url, {
    method,
    headers,
    body: data,
  });
  log(`[${xhrID}] Server responded to ${method} ${url} with status: ${response.status}`);
  return response;
}

// Wrappers for all other HTTP methods that are used by this service
const DELETE = (url, options) => GET(url, options, 'DELETE');
const MKCOL = (url, options) => GET(url, options, 'MKCOL');
const PATCH = (url, options) => GET(url, options, 'PATCH');
const POST = (url, options) => GET(url, options, 'POST');
const PROMOTE = (url, options) => GET(url, options, 'PROMOTE');
const PUT = (url, options) => GET(url, options, 'PUT');
const VERIFY = (url, options) => GET(url, options, 'VERIFY');

// OAuth gateway. Ensures OAuth is set up in the client before proceeding
// If/when OAuth is set up, this calls the original callback with the session data
// and any URL query string args
async function OAuthGate(callback) {
  const QSDict = new URLSearchParams(document.location.search);
  if (QSDict.get('action') === 'oauth') { // OAuth callback?
    const OAuthResponse = await GET(`/api/oauth?${QSDict.toString()}`);
    if (OAuthResponse.status === 200) {
      if (sessionStorageSupported()) {
        const OriginURL = window.sessionStorage.getItem('asp_origin');
        // Do we have a stored URL to redirect back to, now that OAuth worked?
        if (OriginURL) {
          window.sessionStorage.removeItem('asp_origin');
          document.location.href = OriginURL;
        }
        return;
      }
    } else {
      // Something went wrong. For now, just spit out the response as an alert.
      alert(await OAuthResponse.text());
    }
  }
  const session = await GET('/api/session');
  if (session.status === 404) { // No session set for this client yet, run the oauth process
    if (sessionStorageSupported()) {
      window.sessionStorage.setItem('asp_origin', document.location.href); // Store where we came from
    }
    // Construct OAuth URL and redirect to it
    const state = uuid();
    const OAuthURL = encodeURIComponent(`https://${document.location.hostname}/oauth.html?action=oauth&state=${state}`);
    document.location.href = `https://oauth.apache.org/auth?redirect_uri=${OAuthURL}&state=${state}`;
  } else if (session.status === 200) { // Found a working session
    const preferences = await session.json();
    if (callback) callback(preferences, QSDict);
  } else { // Something went wrong on the backend, spit out the error msg
    alert(await session.text());
  }
}


function blur_bg(blur= true) {
  const ctx = document.getElementById('contents');
  if (blur) {
    ctx.style.filter = "blur(5px)";
    ctx.style.userSelect = "none";
  } else {
    ctx.style.filter = "";
    ctx.style.userSelect = "auto";
  }
}

function toast(message, type="danger") {
  const toastdiv = document.getElementById('liveToast');
  if (toastdiv) {
    const toastobj = new bootstrap.Toast(toastdiv);
    toastdiv.querySelector('.toast-header').setAttribute('class', `toast-header text-white bg-${type}`);
    toastdiv.querySelector('.toast-body').innerText = message;
    toastobj.show();
    toastdiv.addEventListener('hide.bs.toast', () => blur_bg(false))
    blur_bg();
  } else {
    alert(message);
  }
}

/********* JIRA ACCOUNT FUNCTIONS *********/
async function jira_seed_project_list() {
  // Seeds the dropdown with current projects
  const projectlist = document.getElementById('project');
  const pubresp = await GET("/api/public");
  const pubdata = await pubresp.json();
  for (project of pubdata.projects) {
    const opt = document.createElement("option");
    opt.text = project;
    opt.value = project;
    projectlist.appendChild(opt);
  }
}

async function jira_account_request_submit(form) {
  const formdata = new FormData(form);
  if (formdata.get("verify") !== "agree") {
    toast("Please agree to sharing your data before submitting your request.");
    return false
  }
  const resp = await POST("/api/jira-account", {data: formdata});
  const result = await resp.json();
  if (!result.success) {
    toast(result.message);
  }
  return false
}
