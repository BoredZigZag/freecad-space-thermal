// SPDX-License-Identifier: MIT OR Apache-2.0
#pragma once
#include <winsock2.h>
#include <windows.h>
#include <charconv>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

// No identity, path, capability SID or socket address is emitted. The manifest
// is local to the supervised acceptance capsule and is never a public artifact.
inline int offline_probe(const char* manifest,const char* port_text) {
  const auto failed=[](const char* stage) {std::cerr<<"offline_probe_"<<stage<<'\n';return 1;};
  HANDLE token=nullptr;
  if(!OpenProcessToken(GetCurrentProcess(),TOKEN_QUERY,&token)) return failed("token");
  DWORD contained=0,bytes=0;
  bool valid=GetTokenInformation(token,TokenIsAppContainer,&contained,sizeof(contained),&bytes)!=0 && contained==1;
  GetTokenInformation(token,TokenCapabilities,nullptr,0,&bytes);
  std::vector<unsigned char> buffer(bytes);
  valid=valid && GetTokenInformation(token,TokenCapabilities,buffer.data(),bytes,&bytes)!=0;
  if(valid) valid=reinterpret_cast<TOKEN_GROUPS*>(buffer.data())->GroupCount==0;
  CloseHandle(token);
  std::ifstream file(manifest);std::string path;unsigned denied=0;
  if(!file) return failed("manifest");
  while(std::getline(file,path)) {
    if(path.empty() || path.size()>32767 || denied>32) return 1;
    const int count=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,path.data(),static_cast<int>(path.size()),nullptr,0);
    if(count<=0) return 1;
    std::wstring wide(static_cast<std::size_t>(count),L'\0');
    if(MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,path.data(),static_cast<int>(path.size()),wide.data(),count)!=count) return 1;
    const HANDLE handle=CreateFileW(wide.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(handle!=INVALID_HANDLE_VALUE) {CloseHandle(handle);return failed("outside_readable");}
    if(GetLastError()!=ERROR_ACCESS_DENIED) return failed("outside_error");
    ++denied;
  }
  if(denied<3) return 1;
  unsigned port=0;
  const std::string port_string(port_text);
  const auto parsed=std::from_chars(port_string.data(),port_string.data()+port_string.size(),port);
  if(parsed.ec!=std::errc{} || parsed.ptr!=port_string.data()+port_string.size() || port==0 || port>65535) return 1;
  WSADATA data{};if(WSAStartup(MAKEWORD(2,2),&data)!=0) return 1;
  const SOCKET connection=socket(AF_INET,SOCK_STREAM,IPPROTO_TCP);
  const int socket_error=connection==INVALID_SOCKET?WSAGetLastError():0;
  const bool socket_denied=connection==INVALID_SOCKET && socket_error==WSAEACCES;
  sockaddr_in address{};address.sin_family=AF_INET;address.sin_port=htons(static_cast<u_short>(port));
  address.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
  u_long nonblocking=1;
  if(!socket_denied && ioctlsocket(connection,FIONBIO,&nonblocking)!=0) {closesocket(connection);WSACleanup();return failed("socket");}
  const int result=socket_denied?SOCKET_ERROR:connect(connection,reinterpret_cast<sockaddr*>(&address),sizeof(address));
  const int connect_error=result==SOCKET_ERROR?WSAGetLastError():0;
  bool network_denied=socket_denied || (result==SOCKET_ERROR && connect_error==WSAEACCES);
  bool timed_drop=false;
  if(!network_denied && result==SOCKET_ERROR && (connect_error==WSAEWOULDBLOCK || connect_error==WSAEINPROGRESS)) {
    fd_set writable,errors;FD_ZERO(&writable);FD_ZERO(&errors);FD_SET(connection,&writable);FD_SET(connection,&errors);
    timeval deadline{5,0};
    const int ready=select(0,nullptr,&writable,&errors,&deadline);
    if(ready==0) {network_denied=true;timed_drop=true;}
    else if(ready>0) {int error=0;int size=sizeof(error);
      if(getsockopt(connection,SOL_SOCKET,SO_ERROR,reinterpret_cast<char*>(&error),&size)==0) network_denied=error==WSAEACCES;}
  }
  closesocket(connection);WSACleanup();
  if(!valid) return failed("capabilities");
  if(!network_denied) return failed("network");
  std::cout<<"{\"status\":\"passed\",\"app_container\":true,\"capabilities\":0,\"network_denied\":true,\"network_denial\":\""
           <<(timed_drop?"controlled_loopback_timeout":"access_denied")<<"\",\"outside_files_denied\":"<<denied<<"}\n";
  return 0;
}
