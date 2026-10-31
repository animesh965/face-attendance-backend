# # # import cv2

# # # for index in range(5):

# # #     print("\nTesting camera index:", index)

# # #     camera = cv2.VideoCapture(
# # #         index,
# # #         cv2.CAP_MSMF
# # #     )

# # #     print("Opened:", camera.isOpened())

# # #     if camera.isOpened():

# # #         success, frame = camera.read()

# # #         print("Frame received:", success)

# # #         if success:
# # #             print("Frame size:", frame.shape)

# # #     camera.release()


# # import cv2

# # for index in range(5):

# #     print("\nTesting:", index)

# #     camera = cv2.VideoCapture(index)

# #     print("Opened:", camera.isOpened())

# #     if camera.isOpened():
# #         ret, frame = camera.read()
# #         print("Frame:", ret)

# #     camera.release()




# import cv2
# import time


# backends = [
#     ("MSMF", cv2.CAP_MSMF),
#     ("DSHOW", cv2.CAP_DSHOW),
# ]


# for name, backend in backends:

#     print("\n====================")
#     print("Backend:", name)

#     for index in range(3):

#         print("Testing camera index:", index)

#         start = time.time()

#         camera = cv2.VideoCapture(
#             index,
#             backend
#         )

#         elapsed = time.time() - start

#         print(
#             "Open time:",
#             round(elapsed, 2),
#             "seconds"
#         )

#         print(
#             "Opened:",
#             camera.isOpened()
#         )


#         if camera.isOpened():

#             ret, frame = camera.read()

#             print(
#                 "Frame received:",
#                 ret
#             )

#             if ret:
#                 print(
#                     "Frame shape:",
#                     frame.shape
#                 )


#         camera.release()