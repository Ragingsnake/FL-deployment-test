# Federated Learning dựa trên Blockchain với cơ chế điều chỉnh trọng số và bảo mật ZKP

Dự án nghiên cứu và xây dựng kiến trúc học liên kết (Federated Learning) an toàn, phi tập trung, tích hợp công nghệ Blockchain và bằng chứng không tiết lộ (Zero-Knowledge Proof) nhằm bảo vệ quyền riêng tư và chống tấn công độc hại.

---

## Tổng quan
Trong kỷ nguyên chuyển đổi số, việc huấn luyện mô hình trên dữ liệu lớn vấp phải rào cản về bảo mật dữ liệu cá nhân. Hệ thống này giải quyết các lỗ hổng của FL truyền thống như:
* **Nguy cơ tấn công:** Poisoning attacks và backdoor.
* **Thiếu minh bạch:** Sự phụ thuộc vào một máy chủ trung tâm không đáng tin cậy.
* **Kiểm soát chất lượng:** Khó kiểm soát tính trung thực của các bản cập nhật từ Client.

## Kiến trúc hệ thống
Hệ thống được chia thành 4 lớp cốt lõi:

1. **Client (Local Training Layer):**
   * Huấn luyện mô hình CNN cục bộ trên tập dữ liệu EMNIST (phân phối Non-IID).
   * Sử dụng **ZK Prover** để tạo bằng chứng ($\pi$) xác nhận quá trình huấn luyện đúng thuật toán.
2. **Decentralized Storage Layer (IPFS):**
   * Lưu trữ các tệp trọng số mô hình có kích thước lớn để giảm tải cho Blockchain.
   * Trả về mã băm định danh nội dung (CID) để tham chiếu.
3. **Blockchain (Consensus & Verification Layer):**
   * Sử dụng mạng **Ethereum Private** với cơ chế đồng thuận **Proof of Authority (PoA)**.
   * **Smart Contract** đóng vai trò là bộ xác thực ZK Verifier và thực thi cơ chế thưởng - phạt.
4. **Aggregation Layer:**
   * Tổng hợp các bản cập nhật đã qua xác thực để tạo mô hình toàn cục (Global Model).

## Các kỹ thuật then chốt
* **Zero-Knowledge Proof (ZKP):** Chứng minh tính hợp lệ của cập nhật mà không làm lộ tham số nhạy cảm hoặc dữ liệu gốc.
* **Adaptive Weight Adjustment:** Điều chỉnh trọng số thích nghi dựa trên chuẩn $L_2$ (Euclidean norm) để giảm ảnh hưởng của các cập nhật bất thường. 
* **Federated Optimization:** Kết hợp **FedProx** tại Client để hạn chế *local drift* và **FedAdam** tại Server để tối ưu tốc độ hội tụ.
* **Reputation-Reward:** Quản lý uy tín Client dựa trên mức độ đóng góp thực tế qua các vòng huấn luyện.

## Công nghệ sủ dụng
* **AI Framework**: **PyTorch** được dùng để xây dựng và huấn luyện mô hình CNN trên tập dữ liệu EMNIST
* **Federated Learning Framework**: **Flower (flwr)** được sử dụng để điều phối quá trình học liên kết giữa Client và Server.
* **Blockchain Development**: **Solidity** dùng để viết các **Smart Contract** thực hiện xác minh ZKP, quản lý uy tín (Reputation) và cơ chế thưởng phạt.



